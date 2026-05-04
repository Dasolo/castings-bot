import asyncio
import logging
from datetime import datetime, timedelta, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from pyrogram import Client, filters
from pyrogram.errors import FloodWait
from pyrogram.types import Message
from sqlalchemy import select, update
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


async def save_message(source: Source, message: Message) -> bool:
    raw_data = {}
    if message.media:
        raw_data["media_type"] = str(message.media)
    if message.forward_from_chat:
        raw_data["forwarded_from"] = message.forward_from_chat.username

    async with AsyncSessionFactory() as session:
        stmt = (
            insert(RawMessage)
            .values(
                source_id=source.id,
                source_type="telegram",
                external_msg_id=str(message.id),
                raw_text=message.text or message.caption,
                raw_data=raw_data or None,
            )
            .on_conflict_do_nothing(
                constraint="raw_messages_source_id_external_msg_id_key"
            )
        )
        result = await session.execute(stmt)
        await session.commit()
        return result.rowcount > 0


async def fetch_history(source: Source) -> None:
    since = datetime.now(timezone.utc) - timedelta(days=settings.history_days)
    log.info("Fetching history for %s since %s", source.external_id, since.date())
    saved = 0
    async for message in app.get_chat_history(source.external_id):
        msg_date = (
            message.date.replace(tzinfo=timezone.utc)
            if message.date.tzinfo is None
            else message.date
        )
        if msg_date < since:
            break
        if message.text or message.caption:
            if await save_message(source, message):
                saved += 1
        await asyncio.sleep(0.05)
    log.info("History done for %s: %d saved", source.external_id, saved)


async def load_sources() -> list[Source]:
    async with AsyncSessionFactory() as session:
        result = await session.execute(
            select(Source).where(
                Source.source_type == "telegram",
                Source.is_active == True,
                Source.verified == True,
            )
        )
        return list(result.scalars().all())


async def send_batch() -> None:
    try:
        result = await app.forward_messages(
            chat_id=user.tg_user_id,
            from_chat_id=source.external_id,
            message_ids=msg_id,
        )
        log.info(
            "Forwarded casting_id=%s to tg_id=%s result=%s",
            casting.id, user.tg_user_id, result,
        )
        async with AsyncSessionFactory() as session:
            users_result = await session.execute(
                select(User).where(User.is_active == True)
            )
            users = users_result.scalars().all()

            if not users:
                return

            user_ids = [u.id for u in users]

            castings_result = await session.execute(
                select(Casting, RawMessage, Source)
                .join(RawMessage, Casting.raw_message_id == RawMessage.id)
                .join(Source, RawMessage.source_id == Source.id)
                .where(
                    ~Casting.id.in_(
                        select(SentLog.casting_id).where(
                            SentLog.user_id.in_(user_ids)
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
            msg_id = int(raw_msg.external_msg_id)
            for user in users:
                try:
                    await app.forward_messages(
                        chat_id=user.tg_user_id,
                        from_chat_id=source.external_id,
                        message_ids=msg_id,
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
                        casting.id, user.tg_user_id, e,
                    )
    except Exception as e:
        log.warning(
            "Failed to forward casting_id=%s to tg_id=%s from_chat=%s msg_id=%s error=%s",
            casting.id, user.tg_user_id, source.external_id, msg_id, e,
        )

async def main() -> None:
    log.info("Starting listener-tg...")
    await app.start()
    log.info("Pyrogram client started")

    sources = await load_sources()
    log.info("Loaded %d verified sources", len(sources))

    for source in sources:
        try:
            await fetch_history(source)
        except FloodWait as e:
            log.warning("FloodWait %ds for %s, skipping history", e.value, source.external_id)

    channel_ids = [s.external_id for s in sources]

    @app.on_message(filters.chat(channel_ids))
    async def on_new_message(client: Client, message: Message) -> None:
        async with AsyncSessionFactory() as session:
            source_result = await session.execute(
                select(Source).where(
                    Source.external_id == message.chat.username,
                    Source.source_type == "telegram",
                )
            )
            source = source_result.scalar_one_or_none()

        if source is None:
            return

        inserted = await save_message(source, message)
        if inserted:
            log.info("Saved new message from %s msg_id=%s", source.external_id, message.id)

    scheduler = AsyncIOScheduler(timezone="UTC")
    scheduler.add_job(send_batch, "interval", minutes=5)
    scheduler.start()

    await send_batch()  # сразу при старте
    await asyncio.Event().wait()


if __name__ == "__main__":
    app.run(main())