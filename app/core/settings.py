from functools import lru_cache
from pathlib import Path
from pydantic import BaseModel


class Settings(BaseModel):
    app_name: str = "Nexa AI API Admin"
    database_url: str = "sqlite:///./data/nexa_admin.db"
    demo_mode: bool = True

    @property
    def sqlite_path(self) -> Path | None:
        if not self.database_url.startswith("sqlite:///"):
            return None
        return Path(self.database_url.replace("sqlite:///", "", 1))


@lru_cache
def get_settings() -> Settings:
    return Settings()
