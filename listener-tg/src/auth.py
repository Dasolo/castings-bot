"""
Interactive first-time authorisation for the Pyrogram userbot.
Run via:  make auth
"""
from pyrogram import Client
from shared.config import settings


def main() -> None:
    app = Client(
        name="/app/sessions/userbot",
        api_id=settings.api_id,
        api_hash=settings.api_hash,
        phone_number=settings.userbot_phone,
    )
    app.run()


if __name__ == "__main__":
    main()
