import asyncio
import logging
from datetime import datetime, timezone

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

    for msg in messages:
        async with AsyncSessionFactory() as session:
            # minimal parser — just copy, no classification yet
            stmt = (
                insert(Casting)
                .values(
                    raw_message_id=msg.id,
                    classified_by=None,
                    is_valid=True,
                )
                .on_conflict_do_nothing()
            )
            await session.execute(stmt)
            await session.execute(
                update(RawMessage)
                .where(RawMessage.id == msg.id)
                .values(parsed_at=datetime.now(timezone.utc))
            )
            await session.commit()

    log.info("Done parsing batch")


async def main() -> None:
    log.info("Starting parser-tg...")
    scheduler = AsyncIOScheduler(timezone="UTC")
    scheduler.add_job(parse_batch, "interval", minutes=2)
    scheduler.start()
    # run once immediately on start
    await parse_batch()
    await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())