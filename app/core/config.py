from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional


class Settings(BaseSettings):
    # Base de données
    DATABASE_URL: str

    # DeepSeek (IA)
    DEEPSEEK_API_KEY: str

    # SerpApi
    SERPAPI_API_KEY: Optional[str] = None

    # Email (SMTP)
    SMTP_HOST: str = "smtp.gmail.com"
    SMTP_PORT: int = 587
    SMTP_USER: str
    SMTP_PASSWORD: str
    EMAIL_FROM: str = "noreply@chatandgo.ci"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
    )


settings = Settings()
