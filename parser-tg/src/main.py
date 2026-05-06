import asyncio
import hashlib
import logging
import re
from datetime import datetime, timezone
from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert

from shared.config import settings
from shared.db import AsyncSessionFactory
from shared.models import Casting, RawMessage

logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Location aliases
# ---------------------------------------------------------------------------

LOCATION_ALIASES: dict[str, list[str]] = {
    "Москва": [
        "москва", "москве", "москву", "москвой", "мск", "moscow",
    ],
    "Московская область": [
        "московская область", "московской области", "подмосковье", "подмосковья",
        "подмосковью", "мособласть", "мо",
    ],
    "Санкт-Петербург": [
        "санкт-петербург", "санкт петербург", "петербург", "питер", "питере",
        "питера", "спб", "с-пб", "saint petersburg", "st. petersburg",
    ],
    "Ленинградская область": [
        "ленинградская область", "ленинградской области", "лен. область",
        "ленобласть", "ленобласти", "ло"
    ],
}

# Flat reverse map: alias → canonical name
_LOCATION_MAP: dict[str, str] = {
    alias: canonical
    for canonical, aliases in LOCATION_ALIASES.items()
    for alias in aliases
}

# Sorted longest-first so "московская область" matches before "москва"
_LOCATION_KEYS = sorted(_LOCATION_MAP.keys(), key=len, reverse=True)


# ---------------------------------------------------------------------------
# Classifier
# ---------------------------------------------------------------------------

def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower()).strip()


def compute_text_hash(text: str) -> str:
    normalized = _normalize(text)
    return hashlib.sha256(normalized.encode()).hexdigest()


def extract_gender(text: str) -> Optional[str]:
    t = _normalize(text)

    # Explicit "male and female" → any
    if re.search(r"(мужчин|парен|актёр|актер).{0,30}(женщин|девушк|актрис)", t):
        return "any"
    if re.search(r"(женщин|девушк|актрис).{0,30}(мужчин|парен|актёр|актер)", t):
        return "any"

    female_pattern = re.compile(
        r"\b(женщин[аыу]?|девушк[аи]?|девочк[аи]?|актрис[аы]?|"
        r"женского пола|дам[аы]?|леди)\b"
    )
    male_pattern = re.compile(
        r"\b(мужчин[аы]?|парен|парня|парни|актёр[а]?|актер[а]?|"
        r"мужского пола|юноша|юноши|мальчик[аи]?|мужик)\b"
    )

    has_female = bool(female_pattern.search(t))
    has_male = bool(male_pattern.search(t))

    if has_female and has_male:
        return "any"
    if has_female:
        return "female"
    if has_male:
        return "male"
    return None


def extract_age(text: str) -> tuple[Optional[int], Optional[int]]:
    t = _normalize(text)

    # Pattern: "25-35 лет", "от 25 до 35"
    range_pattern = re.compile(
        r"(?:от\s*)?(\d{1,2})\s*[-–—до]+\s*(\d{1,2})\s*(?:лет|года?|г\.?)?"
    )
    # Pattern: "до 40 лет"
    max_pattern = re.compile(r"до\s*(\d{1,2})\s*(?:лет|года?|г\.?)")
    # Pattern: "от 18 лет"
    min_pattern = re.compile(r"от\s*(\d{1,2})\s*(?:лет|года?|г\.?)")
    # Pattern: "30 лет" (exact, treat as ±5 range)
    exact_pattern = re.compile(r"(\d{1,2})\s+(?:лет|года?)")

    m = range_pattern.search(t)
    if m:
        a, b = int(m.group(1)), int(m.group(2))
        if 5 <= a <= 100 and 5 <= b <= 100:
            return (min(a, b), max(a, b))

    min_age = max_age = None

    m = max_pattern.search(t)
    if m:
        v = int(m.group(1))
        if 5 <= v <= 100:
            max_age = v

    m = min_pattern.search(t)
    if m:
        v = int(m.group(1))
        if 5 <= v <= 100:
            min_age = v

    if min_age or max_age:
        return (min_age, max_age)

    m = exact_pattern.search(t)
    if m:
        v = int(m.group(1))
        if 5 <= v <= 100:
            return (v, v)

    return (None, None)


def extract_location(text: str) -> Optional[str]:
    t = _normalize(text)
    for key in _LOCATION_KEYS:
        if key in t:
            return _LOCATION_MAP[key]
    return None


def extract_project_type(text: str) -> Optional[str]:
    t = _normalize(text)

    patterns: list[tuple[str, re.Pattern]] = [
        ("ad",      re.compile(r"\b(реклам[аеуы]?|рекламный|рекламного|реклама|коммерческ[аяий]|ролик)\b")),
        ("theatre", re.compile(r"\b(театр[а-я]*|спектакл[а-я]*|постановк[а-я]*)\b")),
        ("series",  re.compile(r"\b(сериал[а-я]*)\b")),
        ("film",    re.compile(r"\b(фильм[а-я]*|кино[а-я]*|кинокартин[а-я]*|короткометражк[а-я]*|полный метр)\b")),
    ]

    for project_type, pattern in patterns:
        if pattern.search(t):
            return project_type
    return None


def extract_fee_type(text: str) -> str:
    t = _normalize(text)

    paid_pattern = re.compile(
        r"\b(оплат[а-я]+|гонорар[а-я]*|платн[а-я]+|оплачивается|"
        r"бюджет|вознаграждени[а-я]+|ставка)\b"
    )
    free_pattern = re.compile(
        r"\b(безвозмездно|бесплатно|без оплаты|волонтёр|волонтер|"
        r"студенческ[а-я]+|дипломн[а-я]+|учебн[а-я]+)\b"
    )

    has_paid = bool(paid_pattern.search(t))
    has_free = bool(free_pattern.search(t))

    if has_paid and not has_free:
        return "paid"
    if has_free and not has_paid:
        return "free"
    return "unknown"


def is_casting_valid(
    gender: Optional[str],
    age_min: Optional[int],
    age_max: Optional[int],
    location: Optional[str],
    project_type: Optional[str],
) -> bool:
    """At least one meaningful field must be extracted."""
    return any([gender, age_min is not None, age_max is not None, location, project_type])


def extract_vacancies(raw_text: str) -> list[dict]:
    """
    Извлекает все вакансии из текста кастинга.
    Возвращает список словарей с полями: gender, age_min, age_max, fee_type, is_valid
    """
    t = _normalize(raw_text)
    vacancies = []

    # TODO: Здесь будет более сложная логика поиска нескольких вакансий
    # Пока что создаем одну вакансию на основе всего текста

    gender = extract_gender(raw_text)
    age_min, age_max = extract_age(raw_text)
    fee_type = extract_fee_type(raw_text)

    # Временная валидация - позже заменим на более умную
    is_valid = any([gender, age_min is not None, age_max is not None])

    vacancies.append({
        "gender": gender,
        "age_min": age_min,
        "age_max": age_max,
        "fee_type": fee_type,
        "fee_max": None,  # TODO: извлекать из текста
        "is_valid": is_valid,
    })

    return vacancies

def classify_with_vacancies(raw_text: str) -> dict:
    """Классифицирует кастинг и извлекает вакансии"""
    vacancies = extract_vacancies(raw_text)

    # Общие поля кастинга (не зависящие от конкретной вакансии)
    location = extract_location(raw_text)
    project_type = extract_project_type(raw_text)

    # Проверяем, есть ли хотя бы одна валидная вакансия
    has_valid_vacancy = any(v["is_valid"] for v in vacancies)

    return {
        "text_hash": compute_text_hash(raw_text),
        "location": location,
        "project_type": project_type,
        "deadline": None,  # TODO: извлекать дедлайн
        "media_file_ids": [],  # TODO: извлекать из raw_data
        "classified_by": "regex",
        "confidence": None,
        "vacancies": vacancies,  # Добавляем вакансии в результат
        "is_valid": has_valid_vacancy,
    }

# ---------------------------------------------------------------------------
# Parser job
# ---------------------------------------------------------------------------

async def parse_batch() -> None:
    async with AsyncSessionFactory() as session:
        result = await session.execute(
            select(RawMessage).where(
                RawMessage.source_type == "telegram",
                RawMessage.parsed_at == None,
                RawMessage.raw_text != None,
            ).limit(100)
        )
        messages = result.scalars().all()

    if not messages:
        return

    log.info("Parsing %d messages", len(messages))
    saved = skipped = 0

    for msg in messages:
        # Получаем классификацию с вакансиями
        fields = classify_with_vacancies(msg.raw_text)

        # Извлекаем вакансии из полей
        vacancies_data = fields.pop("vacancies", [])

        async with AsyncSessionFactory() as session:
            try:
                # 1. Вставляем кастинг (без вакансий)
                stmt = (
                    insert(Casting)
                    .values(raw_message_id=msg.id, **fields)
                    .on_conflict_do_nothing(index_elements=["text_hash"])
                    .returning(Casting.id)
                )
                result = await session.execute(stmt)
                casting_id = result.scalar_one_or_none()

                if casting_id:
                    # 2. Вставляем вакансии для этого кастинга
                    from shared.models import Vacancy

                    for vacancy_data in vacancies_data:
                        vacancy_stmt = insert(Vacancy).values(
                            casting_id=casting_id,
                            **vacancy_data
                        )
                        await session.execute(vacancy_stmt)

                    saved += 1
                    log.debug(
                        "Saved casting id=%d with %d vacancies",
                        casting_id, len(vacancies_data)
                    )
                else:
                    # Дубликат кастинга (по text_hash)
                    skipped += 1
                    log.debug("Skipped duplicate hash=%s", fields["text_hash"])

                # 3. Помечаем raw_message как обработанный
                await session.execute(
                    update(RawMessage)
                    .where(RawMessage.id == msg.id)
                    .values(parsed_at=datetime.now(timezone.utc))
                )
                await session.commit()

            except Exception as e:
                await session.rollback()
                log.error("Failed to process raw_msg_id=%d: %s", msg.id, e)
                raise

    log.info("Batch done: %d saved, %d duplicates", saved, skipped)

async def main() -> None:
    log.info("Starting parser-tg...")
    scheduler = AsyncIOScheduler(timezone="UTC")
    scheduler.add_job(parse_batch, "interval", minutes=2)
    scheduler.start()
    await parse_batch()
    await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())