from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import select

from shared.db import AsyncSessionFactory
from shared.models import User, UserFilter

router = Router()


# ── FSM ──────────────────────────────────────────────────────────────────────

class FiltersFSM(StatesGroup):
    gender        = State()
    age           = State()
    location      = State()
    project_types = State()
    fee_only      = State()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _kb(*buttons: tuple[str, str]) -> InlineKeyboardBuilder:
    """Строит клавиатуру из (label, callback_data)."""
    b = InlineKeyboardBuilder()
    for label, data in buttons:
        b.add(InlineKeyboardButton(text=label, callback_data=data))
    b.adjust(2)
    return b


def _summary(f: UserFilter) -> str:
    gender_map = {"male": "мужской", "female": "женский", "any": "любой", None: "не задан"}
    pts = ", ".join(f.project_types) if f.project_types else "все"
    return (
        "🎛 <b>Текущие фильтры</b>\n\n"
        f"👤 Пол: {gender_map.get(f.gender, '—')}\n"
        f"🎂 Возраст: {f.age if f.age else '—'}\n"
        f"📍 Локация: {f.location or '—'}\n"
        f"🎬 Типы проектов: {pts}\n"
        f"💰 Только платные: {'да' if f.fee_only else 'нет'}"
    )


async def _get_or_create_filter(user_id: int, session) -> UserFilter:
    result = await session.execute(
        select(UserFilter).where(UserFilter.user_id == user_id)
    )
    uf = result.scalar_one_or_none()
    if uf is None:
        uf = UserFilter(user_id=user_id)
        session.add(uf)
        await session.flush()
    return uf


async def _get_db_user(tg_id: int, session) -> User | None:
    result = await session.execute(select(User).where(User.tg_user_id == tg_id))
    return result.scalar_one_or_none()


# ── /filters — точка входа ────────────────────────────────────────────────────

@router.message(F.text == "/filters")
async def cmd_filters(message: Message) -> None:
    async with AsyncSessionFactory() as session:
        user = await _get_db_user(message.from_user.id, session)
        if user is None:
            await message.answer("Сначала введи /start.")
            return

        uf = await _get_or_create_filter(user.id, session)
        await session.commit()

    kb = _kb(
        ("👤 Пол",           "flt:edit:gender"),
        ("🎂 Возраст",       "flt:edit:age"),
        ("📍 Локация",       "flt:edit:location"),
        ("🎬 Тип проекта",   "flt:edit:project_types"),
        ("💰 Только платные","flt:edit:fee_only"),
        ("🗑 Сбросить всё",  "flt:reset"),
    )
    await message.answer(_summary(uf), reply_markup=kb.as_markup(), parse_mode="HTML")


# ── Callback: выбор поля для редактирования ────────────────────────────────────

@router.callback_query(F.data == "flt:edit:gender")
async def edit_gender(cb: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(FiltersFSM.gender)
    kb = _kb(
        ("Мужской", "g:male"),
        ("Женский", "g:female"),
        ("Любой",   "g:any"),
        ("Не важно","g:none"),
    )
    await cb.message.edit_text("Выбери пол:", reply_markup=kb.as_markup())
    await cb.answer()


@router.callback_query(FiltersFSM.gender, F.data.startswith("g:"))
async def save_gender(cb: CallbackQuery, state: FSMContext) -> None:
    value = cb.data.split(":")[1]
    async with AsyncSessionFactory() as session:
        user = await _get_db_user(cb.from_user.id, session)
        uf   = await _get_or_create_filter(user.id, session)
        uf.gender = None if value == "none" else value
        await session.commit()
        summary = _summary(uf)

    await state.clear()
    kb = _main_kb()
    await cb.message.edit_text(summary, reply_markup=kb, parse_mode="HTML")
    await cb.answer("Сохранено ✅")


@router.callback_query(F.data == "flt:edit:age")
async def edit_age(cb: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(FiltersFSM.age)
    await cb.message.edit_text(
        "Введи свой возраст числом (или 0 — сбросить):",
        reply_markup=None,
    )
    await cb.answer()


@router.message(FiltersFSM.age)
async def save_age(message: Message, state: FSMContext) -> None:
    if not message.text.isdigit():
        await message.answer("Введи число, например: 25")
        return
    age = int(message.text)
    async with AsyncSessionFactory() as session:
        user = await _get_db_user(message.from_user.id, session)
        uf   = await _get_or_create_filter(user.id, session)
        uf.age = None if age == 0 else age
        await session.commit()
        summary = _summary(uf)

    await state.clear()
    await message.answer(summary, reply_markup=_main_kb(), parse_mode="HTML")


@router.callback_query(F.data == "flt:edit:location")
async def edit_location(cb: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(FiltersFSM.location)
    await cb.message.edit_text(
        'Введи город, например: <b>Москва</b>\nИли напиши "—" чтобы сбросить.',
        reply_markup=None,
        parse_mode="HTML",
    )
    await cb.answer()


@router.message(FiltersFSM.location)
async def save_location(message: Message, state: FSMContext) -> None:
    value = None if message.text.strip() in ("—", "-", "") else message.text.strip()
    async with AsyncSessionFactory() as session:
        user = await _get_db_user(message.from_user.id, session)
        uf   = await _get_or_create_filter(user.id, session)
        uf.location = value
        await session.commit()
        summary = _summary(uf)

    await state.clear()
    await message.answer(summary, reply_markup=_main_kb(), parse_mode="HTML")


PROJECT_TYPES = [
    ("🎬 Кино",    "film"),
    ("🎭 Театр",   "theatre"),
    ("📺 Сериал",  "series"),
    ("📢 Реклама", "ad"),
]


@router.callback_query(F.data == "flt:edit:project_types")
async def edit_project_types(cb: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(FiltersFSM.project_types)
    async with AsyncSessionFactory() as session:
        user = await _get_db_user(cb.from_user.id, session)
        uf   = await _get_or_create_filter(user.id, session)
        selected: list[str] = list(uf.project_types or [])
    await state.update_data(selected=selected)
    await cb.message.edit_text(
        "Выбери типы проектов (можно несколько):",
        reply_markup=_project_types_kb(selected),
    )
    await cb.answer()


@router.callback_query(FiltersFSM.project_types, F.data.startswith("pt:toggle:"))
async def toggle_project_type(cb: CallbackQuery, state: FSMContext) -> None:
    pt = cb.data.split(":")[2]
    data = await state.get_data()
    selected: list[str] = data.get("selected", [])
    if pt in selected:
        selected.remove(pt)
    else:
        selected.append(pt)
    await state.update_data(selected=selected)
    await cb.message.edit_reply_markup(reply_markup=_project_types_kb(selected))
    await cb.answer()


@router.callback_query(FiltersFSM.project_types, F.data == "pt:save")
async def save_project_types(cb: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    selected: list[str] = data.get("selected", [])
    async with AsyncSessionFactory() as session:
        user = await _get_db_user(cb.from_user.id, session)
        uf   = await _get_or_create_filter(user.id, session)
        uf.project_types = selected or None
        await session.commit()
        summary = _summary(uf)

    await state.clear()
    await cb.message.edit_text(summary, reply_markup=_main_kb(), parse_mode="HTML")
    await cb.answer("Сохранено ✅")


def _project_types_kb(selected: list[str]):
    b = InlineKeyboardBuilder()
    for label, key in PROJECT_TYPES:
        mark = "✅ " if key in selected else ""
        b.add(InlineKeyboardButton(text=f"{mark}{label}", callback_data=f"pt:toggle:{key}"))
    b.adjust(2)
    b.row(InlineKeyboardButton(text="💾 Сохранить", callback_data="pt:save"))
    return b.as_markup()


@router.callback_query(F.data == "flt:edit:fee_only")
async def edit_fee_only(cb: CallbackQuery, state: FSMContext) -> None:
    kb = _kb(
        ("💰 Только платные", "fo:true"),
        ("🆓 Все (включая бесплатные)", "fo:false"),
    )
    await cb.message.edit_text("Показывать только платные кастинги?", reply_markup=kb.as_markup())
    await cb.answer()


@router.callback_query(F.data.startswith("fo:"))
async def save_fee_only(cb: CallbackQuery) -> None:
    value = cb.data == "fo:true"
    async with AsyncSessionFactory() as session:
        user = await _get_db_user(cb.from_user.id, session)
        uf   = await _get_or_create_filter(user.id, session)
        uf.fee_only = value
        await session.commit()
        summary = _summary(uf)

    await cb.message.edit_text(summary, reply_markup=_main_kb(), parse_mode="HTML")
    await cb.answer("Сохранено ✅")


@router.callback_query(F.data == "flt:reset")
async def reset_filters(cb: CallbackQuery) -> None:
    async with AsyncSessionFactory() as session:
        user = await _get_db_user(cb.from_user.id, session)
        uf   = await _get_or_create_filter(user.id, session)
        uf.gender        = None
        uf.age           = None
        uf.location      = None
        uf.project_types = None
        uf.fee_only      = False
        await session.commit()
        summary = _summary(uf)

    await cb.message.edit_text(summary, reply_markup=_main_kb(), parse_mode="HTML")
    await cb.answer("Фильтры сброшены 🗑")


def _main_kb():
    return _kb(
        ("👤 Пол",            "flt:edit:gender"),
        ("🎂 Возраст",        "flt:edit:age"),
        ("📍 Локация",        "flt:edit:location"),
        ("🎬 Тип проекта",    "flt:edit:project_types"),
        ("💰 Только платные", "flt:edit:fee_only"),
        ("🗑 Сбросить всё",   "flt:reset"),
    ).as_markup()