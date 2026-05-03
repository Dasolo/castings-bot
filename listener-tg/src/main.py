import asyncio
import logging
from datetime import datetime, timedelta, timezone

from pyrogram import Client, filters
from pyrogram.errors import FloodWait
from pyrogram.types import Message
from sqlalchemy import select, update
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
    """Save a single message. Returns True if inserted, False if duplicate."""
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
            .on_conflict_do_nothing(constraint="raw_messages_source_id_external_msg_id_key")
        )
        result = await session.execute(stmt)
        await session.commit()
        return result.rowcount > 0


async def fetch_history(source: Source) -> None:
    """Fetch last HISTORY_DAYS days of messages for a source."""
    since = datetime.now(timezone.utc) - timedelta(days=settings.history_days)
    log.info("Fetching history for %s since %s", source.external_id, since.date())

    saved = 0
    async for message in app.get_chat_history(source.external_id):
        if message.date < since:
            break
        if message.text or message.caption:
            if await save_message(source, message):
                saved += 1
        await asyncio.sleep(0.05)  # be gentle

    log.info("History fetch done for %s: %d messages saved", source.external_id, saved)


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


async def resolve_and_update_source(source: Source) -> Source:
    """Resolve username to numeric channel id and update DB."""
    try:
        chat = await app.get_chat(source.external_id)
        numeric_id = str(chat.id)
        if source.external_id != numeric_id:
            async with AsyncSessionFactory() as session:
                await session.execute(
                    update(Source)
                    .where(Source.id == source.id)
                    .values(external_id=numeric_id, title=chat.title or source.title)
                )
                await session.commit()
            log.info("Resolved %s → %s (%s)", source.external_id, numeric_id, chat.title)
            source.external_id = numeric_id
    except Exception as e:
        log.warning("Could not resolve source %s: %s", source.external_id, e)
    return source


async def main() -> None:
    log.info("Starting listener-tg...")

    await app.start()
    log.info("Pyrogram client started")

    sources = await load_sources()
    log.info("Loaded %d verified sources", len(sources))

    # Resolve usernames to numeric ids and fetch history
    for source in sources:
        source = await resolve_and_update_source(source)
        try:
            await fetch_history(source)
        except FloodWait as e:
            log.warning("FloodWait %ds while fetching history for %s, skipping",
                        e.value, source.external_id)

    # Register handler for new messages from our channels
    channel_ids = [int(s.external_id) for s in sources if s.external_id.lstrip("-").isdigit()]

    @app.on_message(filters.chat(channel_ids))
    async def on_new_message(client: Client, message: Message) -> None:
        async with AsyncSessionFactory() as session:
            source_result = await session.execute(
                select(Source).where(
                    Source.external_id == str(message.chat.id),
                    Source.source_type == "telegram",
                )
            )
            source = source_result.scalar_one_or_none()

        if source is None:
            log.warning("Received message from unknown source chat_id=%s", message.chat.id)
            return

        inserted = await save_message(source, message)
        if inserted:
            log.info("Saved new message from %s msg_id=%s", source.external_id, message.id)

    log.info("Listening for new messages in %d channels", len(channel_ids))
    await asyncio.Event().wait()


if __name__ == "__main__":
    app.run(main())