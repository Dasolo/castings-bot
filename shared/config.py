from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    bot_token: str = ""
    api_id: int = 0
    api_hash: str = ""
    userbot_phone: str = ""

    database_url: str = ""
    debug: bool = False
    history_days: int = 3


settings = Settings()
