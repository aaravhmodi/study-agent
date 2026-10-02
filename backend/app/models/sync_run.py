from datetime import datetime
from uuid import uuid4

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


class SyncRun(Base):
    __tablename__ = "sync_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    courses_found: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    assessments_found: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    resources_found: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    changes_found: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
