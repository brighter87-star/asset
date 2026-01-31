import os
from pathlib import Path

from dotenv import load_dotenv
from pydantic_settings import BaseSettings

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


class Settings(BaseSettings):
    # Kiwoom API credentials
    APP_KEY: str
    SECRET_KEY: str
    BASE_URL: str
    SOCKET_URL: str
    ACNT_API_ID: str

    # Database configuration (asset DB)
    DB_HOST: str
    DB_USER: str
    DB_PASSWORD: str
    DB_NAME: str = "asset"  # Default to 'asset' database

    # Trading database (for syncing)
    TRADING_DB_NAME: str = "trading"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
