"""
Database layer - SQLAlchemy models for the renders table.

Connection string comes from the DATABASE_URL environment variable
(loaded from a local .env file). Falls back to SQLite for quick local runs.
"""

import os
import uuid
from datetime import datetime, timezone

from dotenv import load_dotenv
from sqlalchemy import (
    create_engine, Column, String, DateTime, Float, Integer, Text
)
from sqlalchemy.orm import declarative_base, sessionmaker, Session

load_dotenv()  # reads .env next to this file (never committed to Git)

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./stylized_renderer.db")

# SQLite needs a special flag; PostgreSQL does not
connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(
    DATABASE_URL,
    connect_args=connect_args,
    echo=False,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class Render(Base):
    """
    Tracks every render job from submission to completion.

    id               : UUID primary key
    task_id          : Celery task ID
    user_id          : Anonymous session ID or auth user ID
    original_url     : storage URL of the uploaded original image
    stylized_url     : storage URL of the processed image (NULL until done)
    status           : queued | processing | success | failed
    k_colors, edge_method, bilateral_passes : pipeline parameters (audit/replay)
    processing_s     : seconds the stylize() call took
    error_message    : if status=failed, what went wrong
    created_at / completed_at : UTC timestamps
    """
    __tablename__ = "renders"

    id             = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    task_id        = Column(String(255), unique=True, nullable=False, index=True)
    user_id        = Column(String(255), nullable=True, index=True)

    original_url   = Column(Text, nullable=True)
    stylized_url   = Column(Text, nullable=True)

    status         = Column(String(50), default="queued", nullable=False)

    k_colors         = Column(Integer, default=12)
    edge_method      = Column(String(20), default="canny")
    bilateral_passes = Column(Integer, default=3)

    processing_s   = Column(Float, nullable=True)
    error_message  = Column(Text, nullable=True)

    created_at     = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    completed_at   = Column(DateTime, nullable=True)

    def to_dict(self) -> dict:
        return {
            "id":               self.id,
            "task_id":          self.task_id,
            "user_id":          self.user_id,
            "original_url":     self.original_url,
            "stylized_url":     self.stylized_url,
            "status":           self.status,
            "k_colors":         self.k_colors,
            "edge_method":      self.edge_method,
            "bilateral_passes": self.bilateral_passes,
            "processing_s":     self.processing_s,
            "error_message":    self.error_message,
            "created_at":       self.created_at.isoformat() if self.created_at else None,
            "completed_at":     self.completed_at.isoformat() if self.completed_at else None,
        }

    def __repr__(self):
        return f"<Render id={self.id} status={self.status}>"


def init_db():
    """Create all tables if they don't exist yet."""
    Base.metadata.create_all(bind=engine)


def get_db() -> Session:
    """FastAPI dependency that yields a session and closes it afterwards."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()