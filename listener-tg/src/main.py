import asyncio
import logging
from datetime import datetime, timedelta, timezone

from pyrogram import Client, filters
from pyrogram.errors import FloodWait
from pyrogram.types import Message
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from shared.config import settings
from shared.db import AsyncSessionFactory
from shared.models import RawMessage, Source

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


async def main() -> None:
    log.info("Starting listener-tg...")
    await app.start()

    me = await app.get_me()
    log.info("Logged in as %s (id=%s)", me.username, me.id)

    sources = await load_sources()
    log.info("Loaded %d verified sources", len(sources))

    for source in sources:
        try:
            await fetch_history(source)
        except FloodWait as e:
            log.warning("FloodWait %ds for %s, skipping history", e.value, source.external_id)

    # Строим маппинг числовой_id → source (надёжнее username)
    source_by_id: dict[int, Source] = {}
    source_by_username: dict[str, Source] = {}

    for source in sources:
        try:
            chat = await app.get_chat(source.external_id)
            source_by_id[chat.id] = source
            if chat.username:
                source_by_username[chat.username.lower()] = source
            log.info("Channel check: %s → id=%s type=%s members=%s",
                    source.external_id, chat.id, chat.type, chat.members_count)
        except Exception as e:
            log.warning("Channel check failed for %s: %s", source.external_id, e)

    channel_numeric_ids = list(source_by_id.keys())
    log.info("Registered handler for channel ids: %s", channel_numeric_ids)

    @app.on_message(filters.chat(channel_numeric_ids))
    async def on_new_message(client: Client, message: Message) -> None:
        log.info(
            "Received message from chat_id=%s username=%s msg_id=%s",
            message.chat.id, message.chat.username, message.id,
        )

        source = source_by_id.get(message.chat.id)
        if source is None and message.chat.username:
            source = source_by_username.get(message.chat.username.lower())

        if source is None:
            log.warning("Source not found for chat_id=%s", message.chat.id)
            return

        inserted = await save_message(source, message)
        if inserted:
            log.info("Saved new message from %s msg_id=%s", source.external_id, message.id)

    @app.on_message()
    async def on_any_message(client: Client, message: Message) -> None:
        log.info(
            "ANY message: chat_id=%s username=%s type=%s",
            message.chat.id, message.chat.username, message.chat.type,
        )

    log.info("Listening on %d channels", len(channel_numeric_ids))
    await asyncio.Event().wait()


if __name__ == "__main__":
    app.run(main())