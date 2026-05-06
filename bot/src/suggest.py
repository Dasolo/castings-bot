import logging
import re

from aiogram import Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from shared.db import AsyncSessionFactory
from shared.models import Source, User

log = logging.getLogger(__name__)

router = Router()

# Принимаем: @username, t.me/username, https://t.me/username
_TG_LINK_RE = re.compile(
    r"(?:https?://)?t\.me/([A-Za-z0-9_]{5,})"
    r"|@([A-Za-z0-9_]{5,})"
    r"|^([A-Za-z0-9_]{5,})$"
)


def _parse_username(text: str) -> str | None:
    """Извлекает username без @. Возвращает None если не распознано."""
    m = _TG_LINK_RE.search(text.strip())
    if not m:
        return None
    return (m.group(1) or m.group(2) or m.group(3)).lstrip("@").lower()


class SuggestStates(StatesGroup):
    waiting_for_channel = State()


@router.message(Command("suggest"))
async def cmd_suggest(message: Message, state: FSMContext) -> None:
    await state.set_state(SuggestStates.waiting_for_channel)
    await message.answer(
        "Пришли ссылку на канал или его @username.\n"
        "Например: @APTUCTbI или https://t.me/APTUCTbI\n\n"
        "Отмена — /cancel"
    )


@router.message(Command("cancel"), SuggestStates.waiting_for_channel)
async def cmd_cancel(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Отменено.")


@router.message(SuggestStates.waiting_for_channel)
async def process_channel(message: Message, state: FSMContext) -> None:
    username = _parse_username(message.text or "")

    if not username:
        await message.answer(
            "Не смог распознать канал. Пришли @username или ссылку t.me/..."
        )
        return

    async with AsyncSessionFactory() as session:
        # Определяем user_id по tg_user_id
        result = await session.execute(
            select(User).where(User.tg_user_id == message.from_user.id)
        )
        user = result.scalar_one_or_none()
        user_id = user.id if user else None

        # Проверяем, не добавлен ли уже
        existing = await session.execute(
            select(Source).where(
                Source.source_type == "telegram",
                Source.external_id == username,
            )
        )
        source = existing.scalar_one_or_none()

        if source is not None:
            await state.clear()
            status = "уже верифицирован ✅" if source.verified else "уже в очереди на проверку ⏳"
            await message.answer(f"Канал @{username} {status}. Спасибо!")
            return

        new_source = Source(
            source_type="telegram",
            external_id=username,
            is_active=False,   # активируем только после верификации
            verified=False,
            added_by=user_id,
        )
        session.add(new_source)
        try:
            await session.commit()
            log.info(
                "New source suggested: @%s by tg_user_id=%s",
                username,
                message.from_user.id,
            )
        except IntegrityError:
            await session.rollback()
            await message.answer(f"Канал @{username} уже предложен. Спасибо!")
            await state.clear()
            return

    await state.clear()
    await message.answer(
        f"Спасибо! Канал @{username} отправлен на проверку. "
        "После верификации администратором он появится в списке источников. 🎭"
    )
