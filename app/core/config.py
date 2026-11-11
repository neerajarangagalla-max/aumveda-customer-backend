from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


BASE_DIR = Path(__file__).resolve().parents[2]
ENV_FILE = BASE_DIR / ".env"


class Settings(BaseSettings):
    app_name: str = "AUMVEDA Backend"
    app_env: str = "development"

    host: str = "0.0.0.0"
    port: int = 8001

    api_v1_prefix: str = "/api/v1"

    supabase_url: str

    supabase_anon_key: str | None = None
    supabase_secret_key: str | None = None
    supabase_service_role_key: str | None = None

    frontend_url: str = "http://localhost:5173"
    mobile_reset_url: str = "aumveda://reset-password"

    cors_origins: str = ""

    model_config = SettingsConfigDict(
        env_file=str(ENV_FILE),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @property
    def allowed_origins(self) -> list[str]:
        return [
            origin.strip()
            for origin in self.cors_origins.split(",")
            if origin.strip()
        ]

    @property
    def auth_client_key(self) -> str:
        if not self.supabase_anon_key:
            raise ValueError("SUPABASE_ANON_KEY is not configured")
        return self.supabase_anon_key

    @property
    def admin_client_key(self) -> str:
        if not self.supabase_service_role_key:
            raise ValueError("SUPABASE_SERVICE_ROLE_KEY is not configured")
        return self.supabase_service_role_key


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()