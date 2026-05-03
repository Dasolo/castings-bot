import asyncio
import logging

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)


async def main() -> None:
    log.info("Starting %s...", __package__)
    # TODO: implement
    await asyncio.sleep(3600)


if __name__ == "__main__":
    asyncio.run(main())
