"""
Settings for asset management system.
All sensitive values are loaded from .env file.
"""

from pathlib import Path
from pydantic_settings import BaseSettings

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """
    Application settings loaded from .env file.
    Create a .env file in the project root with your credentials.
    See .env.example for template.
    """

    # Kiwoom API credentials
    APP_KEY: str
    SECRET_KEY: str
    BASE_URL: str
    SOCKET_URL: str = ""  # Optional
    ACNT_API_ID: str

    # Database configuration
    DB_HOST: str = "localhost"
    DB_USER: str
    DB_PASSWORD: str
    DB_NAME: str = "asset"

    model_config = {
        "env_file": str(BASE_DIR / ".env"),
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }
