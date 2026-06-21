from sqlalchemy import true
from enum import Enum
from sqlalchemy import Float
from sqlalchemy import String, Integer, DateTime, ForeignKey, Text, JSON, UUID
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func
from .database import Base
import uuid
import cloudinary
import cloudinary.uploader
import os
from sqlalchemy import Enum as SQLEnum

from dotenv import load_dotenv
load_dotenv()

cloudinary.config(
    cloud_name=os.getenv("CLOUDINARY_CLOUD_NAME"),
    api_key=os.getenv("CLOUDINARY_API_KEY"),
    api_secret=os.getenv("CLOUDINARY_API_SECRET"),
    secure=True  # Forces HTTPS URLs
)

class PlanEnum(str, Enum):
    FREE = "free"
    PRO = "pro"
    ULTRA = "ultra"

class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    email: Mapped[str] = mapped_column(String, unique = True, nullable=False)
    username: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    password: Mapped[str] = mapped_column(String, nullable=True)
    plan : Mapped[str] = mapped_column(SQLEnum(PlanEnum), nullable=True, default=PlanEnum.FREE)
    jobs: Mapped[list["Job"]] = relationship("Job", back_populates="user")

class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False, default="pending")
    result: Mapped[dict] = mapped_column(JSON().with_variant(JSONB, "postgresql"), nullable=True)
    error: Mapped[str] = mapped_column(Text, nullable=True)
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), nullable=True)
    time_taken: Mapped[float] = mapped_column(Float, nullable=True)
    image_url: Mapped[str] = mapped_column(String, nullable=True)
    cloudinary_public_id: Mapped[str] = mapped_column(String, nullable=True) 
    user: Mapped["User"] = relationship("User", back_populates="jobs")

class RateLimit(Base):
    __tablename__ = "rate_limits"

    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    request_count: Mapped[int] = mapped_column(Integer, default=0)
    window_start: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now())