from datetime import datetime
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


class Course(Base):
    __tablename__ = "courses"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    external_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    code: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    term: Mapped[str | None] = mapped_column(String(100), nullable=True)
    url: Mapped[str] = mapped_column(String(2048), nullable=False, unique=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_scanned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    assessments = relationship("Assessment", back_populates="course", cascade="all, delete-orphan")
    announcements = relationship(
        "Announcement", back_populates="course", cascade="all, delete-orphan"
    )
    resources = relationship("Resource", back_populates="course", cascade="all, delete-orphan")
    topics = relationship("Topic", back_populates="course", cascade="all, delete-orphan")
