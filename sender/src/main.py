import asyncio
import logging
from datetime import datetime, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from pyrogram import Client
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from shared.config import settings
from shared.db import AsyncSessionFactory
from shared.models import Casting, RawMessage, SentLog, Source, User

logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger(__name__)

app = Client(
    name="/app/sessions/userbot",
    api_id=settings.api_id,
    api_hash=settings.api_hash,
)


async def send_batch() -> None:
    async with AsyncSessionFactory() as session:
        # все активные пользователи
        users_result = await session.execute(
            select(User).where(User.is_active == True)
        )
        users = users_result.scalars().all()

        if not users:
            return

        # кастинги которые ещё не отправлены хотя бы одному юзеру
        # берём через left join с sent_log
        castings_result = await session.execute(
            select(Casting, RawMessage, Source)
            .join(RawMessage, Casting.raw_message_id == RawMessage.id)
            .join(Source, RawMessage.source_id == Source.id)
            .where(
                ~Casting.id.in_(
                    select(SentLog.casting_id).where(
                        SentLog.user_id.in_([u.id for u in users])
                    )
                )
            )
            .order_by(Casting.created_at)
            .limit(50)
        )
        rows = castings_result.all()

    if not rows:
        log.info("No new castings to send")
        return

    log.info("Sending %d castings to %d users", len(rows), len(users))

    for casting, raw_msg, source in rows:
        for user in users:
            try:
                await app.forward_messages(
                    chat_id=user.tg_user_id,
                    from_chat_id=source.external_id,
                    message_ids=int(raw_msg.external_msg_id),
                )
                async with AsyncSessionFactory() as session:
                    await session.execute(
                        insert(SentLog)
                        .values(user_id=user.id, casting_id=casting.id)
                        .on_conflict_do_nothing()
                    )
                    await session.commit()
                await asyncio.sleep(0.05)
            except Exception as e:
                log.warning(
                    "Failed to forward casting_id=%s to tg_id=%s: %s",
                    casting.id, user.tg_user_id, e
                )


async def main() -> None:
    log.info("Starting sender...")
    await app.start()
    log.info("Pyrogram client started")

    scheduler = AsyncIOScheduler(timezone="UTC")
    scheduler.add_job(send_batch, "interval", minutes=5)
    scheduler.start()

    await send_batch()  # сразу при старте
    await asyncio.Event().wait()


if __name__ == "__main__":
    app.run(main())