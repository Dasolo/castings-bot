import asyncio
import logging

from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import selectinload

from shared.config import settings
from shared.db import AsyncSessionFactory
from shared.models import Casting, RawMessage, SentLog, Source, User

logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger(__name__)

def _matches(casting: Casting, uf) -> bool:
    """True если кастинг проходит фильтр пользователя."""
    if uf is None:
        return True  # фильтров нет — слать всё

    # Локация
    if uf.location and casting.location:
        if uf.location.lower() not in casting.location.lower():
            return False

    # Тип проекта
    if uf.project_types and casting.project_type:
        if casting.project_type not in uf.project_types:
            return False

    # Только платные
    if uf.fee_only:
        has_paid = any(v.fee_type == "paid" for v in casting.vacancies)
        if not has_paid:
            return False

    # Пол и возраст — матчим по вакансиям
    if uf.gender or uf.age:
        matched_vacancy = False
        for v in casting.vacancies:
            gender_ok = (
                not uf.gender
                or v.gender in (uf.gender, "any", None)
            )
            age_ok = (
                not uf.age
                or (
                    (v.age_min is None or v.age_min <= uf.age)
                    and (v.age_max is None or v.age_max >= uf.age)
                )
            )
            if gender_ok and age_ok:
                matched_vacancy = True
                break
        if casting.vacancies and not matched_vacancy:
            return False
        # если вакансий нет — пропускаем (парсер ещё не разобрал)

    return True


async def send_batch(bot: Bot) -> None:
    async with AsyncSessionFactory() as session:

        users_result = await session.execute(
            select(User)
            .where(User.is_active == True)
            .options(selectinload(User.filters))
        )
        users = users_result.scalars().all()

        if not users:
            return

        user_ids = [u.id for u in users]

        castings_result = await session.execute(
            select(Casting, RawMessage, Source)
            .join(RawMessage, Casting.raw_message_id == RawMessage.id)
            .join(Source, RawMessage.source_id == Source.id)
            .options(selectinload(Casting.vacancies))   # ← добавить
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
        link = f"https://t.me/{source.external_id}/{msg_id}"

        for user in users:
            if not _matches(casting, user.filters):
                continue
            try:
                await bot.send_message(
                    chat_id=user.tg_user_id,
                    text=link,
                )
                async with AsyncSessionFactory() as session:
                    await session.execute(
                        insert(SentLog)
                        .values(user_id=user.id, casting_id=casting.id)
                        .on_conflict_do_nothing()
                    )
                    await session.commit()
                await asyncio.sleep(0.05)
                log.info("Sent casting_id=%s to tg_id=%s", casting.id, user.tg_user_id)
            except Exception as e:
                log.warning(
                    "Failed to send casting_id=%s to tg_id=%s: %s",
                    casting.id, user.tg_user_id, e,
                )


async def main() -> None:
    log.info("Starting sender...")
    bot = Bot(token=settings.bot_token)

    scheduler = AsyncIOScheduler(timezone="UTC")
    scheduler.add_job(send_batch, "interval", minutes=5, args=[bot])
    scheduler.start()

    await send_batch(bot)
    await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())