import asyncio
import logging

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
)
from sqlalchemy import select

from shared.config import settings
from shared.db import AsyncSessionFactory
from shared.models import User
from .keyboards import main_menu_kb
from .filters import router as filters_router
from .suggest import router as suggest_router

logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger(__name__)

async def cmd_start(message: Message) -> None:
    tg_id = message.from_user.id
    username = message.from_user.username

    async with AsyncSessionFactory() as session:
        result = await session.execute(
            select(User).where(User.tg_user_id == tg_id)
        )
        user = result.scalar_one_or_none()

        if user is None:
            user = User(tg_user_id=tg_id, username=username)
            session.add(user)
            await session.commit()
            log.info("Registered new user tg_id=%s username=%s", tg_id, username)
            await message.answer(
                "Привет! Ты зарегистрирован.\n"
                "Скоро здесь появятся кастинги. 🎭",
                reply_markup=main_menu_kb(),
            )
        else:
            if user.username != username:
                user.username = username
                await session.commit()
            await message.answer(
                "Ты уже зарегистрирован. Ждём кастингов! 🎭",
                reply_markup=main_menu_kb(),
            )


async def cmd_fallback(message: Message, state: FSMContext) -> None:
    """Всё что не поймали роутеры — показываем главное меню."""
    print(f"[DEBUG] Fallback triggered for: {message.text}")
    current_state = await state.get_state()
    if current_state is not None:
        # Внутри FSM — не перебиваем
        return
    await message.answer(
        "Выбери действие:",
        reply_markup=main_menu_kb(),
    )


async def main() -> None:
    log.info("Starting bot...")
    bot = Bot(token=settings.bot_token)
    dp = Dispatcher()

    dp.message.register(cmd_start, CommandStart())
    dp.include_router(filters_router)
    dp.include_router(suggest_router)

    # Fallback — регистрируем последним, чтобы не перехватывать FSM-сообщения
    dp.message.register(cmd_fallback, F.text)

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
