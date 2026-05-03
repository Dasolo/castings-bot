import asyncio
import logging
from datetime import datetime, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import func, select

from shared.config import settings
from shared.db import AsyncSessionFactory
from shared.models import Casting, User

logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger(__name__)

# при рестарте сбрасывается на момент запуска — это нормально
_last_run: datetime = datetime.now(timezone.utc)


async def notify_users() -> None:
    global _last_run
    since = _last_run
    _last_run = datetime.now(timezone.utc)

    async with AsyncSessionFactory() as session:
        # считаем новые кастинги с прошлого запуска
        count_result = await session.execute(
            select(func.count()).where(Casting.created_at >= since)
        )
        new_count = count_result.scalar_one()

        # берём всех активных пользователей
        users_result = await session.execute(
            select(User).where(User.is_active == True)
        )
        users = users_result.scalars().all()

    if not users:
        log.info("No active users, skipping")
        return

    log.info("New castings since %s: %d, sending to %d users", since, new_count, len(users))

    from aiogram import Bot
    bot = Bot(token=settings.bot_token)

    text = (
        f"🎭 Новых кастингов за последние 5 минут: {new_count}"
        if new_count > 0
        else "📭 Новых кастингов нет"
    )

    for user in users:
        try:
            await bot.send_message(user.tg_user_id, text)
            await asyncio.sleep(0.05)  # TG rate limit 30 msg/sec
        except Exception as e:
            log.warning("Failed to send to tg_id=%s: %s", user.tg_user_id, e)

    await bot.session.close()


async def main() -> None:
    log.info("Starting sender...")
    scheduler = AsyncIOScheduler(timezone="UTC")
    scheduler.add_job(notify_users, "interval", minutes=1)
    scheduler.start()
    log.info("Scheduler started, first run in 5 minutes")
    await asyncio.Event().wait()  # держим процесс живым


if __name__ == "__main__":
    asyncio.run(main())