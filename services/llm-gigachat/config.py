"""
Единый конфиг приложения через Pydantic Settings.
Все настройки читаются из .env или переменных окружения.
"""
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=Path(__file__).parent / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- GigaChat ---
    giga_base_url: str = "https://api.giga.chat/v1"
    giga_scope: str = "GIGACHAT_API_PERS"
    giga_model: str = "GigaChat-3-Ultra"
    giga_password: str
    ca_bundle_file: str = "russian_trusted_root_ca_pem.crt"

    # --- HTTP ---
    giga_service_url: str = "http://127.0.0.1:8001"
    app_port: int = 8000
    giga_port: int = 8001
    http_timeout: float = 60.0

    # --- Правила и данные ---
    rules_path: str = "gost_32775_2014_rules.xlsx"
    db_path: str = "results.db"

    # --- Классификатор ---
    warning_tolerance_percent: float = 5.0

    # --- Логирование ---
    log_level: str = "INFO"
    log_file: str = "logs/agent.log"


settings = Settings()