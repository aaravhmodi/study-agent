from collections.abc import Generator
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings


class Base(DeclarativeBase):
    pass


def _database_url() -> str:
    url = get_settings().database_url
    if url.startswith("sqlite:///") and not url.startswith("sqlite:////"):
        relative_path = url.removeprefix("sqlite:///")
        absolute_path = Path(get_settings().project_root, relative_path).resolve()
        absolute_path.parent.mkdir(parents=True, exist_ok=True)
        return f"sqlite:///{absolute_path.as_posix()}"
    return url


_resolved_database_url = _database_url()
engine = create_engine(
    _resolved_database_url,
    connect_args={"check_same_thread": False}
    if _resolved_database_url.startswith("sqlite")
    else {},
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    with SessionLocal() as session:
        yield session
