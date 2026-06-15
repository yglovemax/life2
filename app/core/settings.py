from functools import lru_cache
import os
from pathlib import Path
from pydantic import BaseModel


class Settings(BaseModel):
    app_name: str = "Nexa AI API Admin"
    database_url: str = "sqlite:///./data/nexa_admin.db"
    demo_mode: bool = True
    app_api_token: str = os.environ.get("NEXA_APP_API_TOKEN", "dev-app-token")
    admin_username: str = os.environ.get("NEXA_ADMIN_USERNAME", "admin")
    admin_password: str = os.environ.get("NEXA_ADMIN_PASSWORD", "admin123")
    admin_auth_required: bool = os.environ.get("NEXA_ADMIN_AUTH_REQUIRED", "").lower() in {"1", "true", "yes", "on"}

    @property
    def sqlite_path(self) -> Path | None:
        if not self.database_url.startswith("sqlite:///"):
            return None
        return Path(self.database_url.replace("sqlite:///", "", 1))


@lru_cache
def get_settings() -> Settings:
    return Settings()
