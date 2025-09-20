# app/config.py
from typing import Literal
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    # App
    APP_ENV: Literal["dev", "prod", "staging"] = "dev"
    TZ: str = "Europe/London"

    # OpenAI
    OPENAI_API_KEY: str
    OPENAI_MODEL: str = "gpt-4o-mini"

    # Amadeus
    AMADEUS_CLIENT_ID: str
    AMADEUS_CLIENT_SECRET: str
    AMADEUS_ENV: str = "sandbox"  # or "production"

    # Twilio
    TWILIO_ACCOUNT_SID: str
    TWILIO_AUTH_TOKEN: str
    TWILIO_WHATSAPP_NUMBER: str

    # read .env and ignore any extra keys so this doesn't break again
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

settings = Settings()
