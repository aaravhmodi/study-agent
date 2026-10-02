from datetime import datetime
from uuid import uuid4

from sqlalchemy import DateTime, Float, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


class Topic(Base):
    __tablename__ = "topics"
    __table_args__ = (UniqueConstraint("course_id", "name", name="uq_topic_course_name"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    course_id: Mapped[str] = mapped_column(
        ForeignKey("courses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_resource_id: Mapped[str | None] = mapped_column(
        ForeignKey("resources.id", ondelete="SET NULL"), nullable=True
    )
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    mastery: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="NOT_STARTED")

    course = relationship("Course", back_populates="topics")
