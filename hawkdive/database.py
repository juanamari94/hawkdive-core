from pathlib import Path

from alembic.config import Config
from sqlalchemy import URL


def database_url(path: Path, *, asynchronous: bool = True) -> URL:
    driver = 'sqlite+aiosqlite' if asynchronous else 'sqlite'
    return URL.create(driver, database=str(path.resolve()))


def migration_config() -> Config:
    return Config(str(Path(__file__).resolve().parents[1] / 'alembic.ini'))
