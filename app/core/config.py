from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # ---------------------------------------------------------
    # APPLICATION
    # ---------------------------------------------------------

    app_name: str = "AUMVEDA Backend"
    app_env: str = "development"

    host: str = "0.0.0.0"
    port: int = 5000

    api_v1_prefix: str = "/api/v1"


    # ---------------------------------------------------------
    # SUPABASE
    # ---------------------------------------------------------

    supabase_url: str

    supabase_anon_key: str | None = None
    supabase_secret_key: str | None = None
    supabase_service_role_key: str | None = None


    # ---------------------------------------------------------
    # FRONTEND / MOBILE
    # ---------------------------------------------------------

    frontend_url: str = "http://localhost:5173"

    mobile_reset_url: str = "aumveda://reset-password"


    # ---------------------------------------------------------
    # CORS
    # ---------------------------------------------------------

    
    # ---------------------------------------------------------
    # CORS
    # ---------------------------------------------------------

    cors_origins: str = (
        "http://localhost:5173,"
        "http://127.0.0.1:5173,"
        "http://localhost:8081,"
        "http://127.0.0.1:8081,"
        "http://192.168.0.31:8081"
    )



    model_config = SettingsConfigDict(
        env_file=".env",
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
        return (
            self.supabase_anon_key
            or self.supabase_secret_key
            or ""
        )


    @property
    def admin_client_key(self) -> str:
        return (
            self.supabase_service_role_key
            or self.supabase_secret_key
            or ""
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()