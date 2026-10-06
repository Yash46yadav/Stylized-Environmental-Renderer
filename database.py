"""
Phase 4: Database Layer – SQLAlchemy Models
============================================
We use SQLAlchemy (the most popular Python ORM) to define our database schema
as Python classes, so we never write raw SQL.

Key SQLAlchemy concepts
-----------------------
• Engine      – the connection to the database (PostgreSQL, SQLite, etc.)
• Session     – a "unit of work"; all queries go through a session
• Base        – declarative base class every model inherits from
• Column      – maps a Python attribute to a DB column
• relationship– defines foreign-key joins as Python object attributes

In production → DATABASE_URL = "postgresql://user:pass@host:5432/dbname"
For local dev  → DATABASE_URL = "sqlite:///./dev.db"  (no Postgres install needed)
"""

import os
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    create_engine, Column, String, DateTime, Float, Integer, Text
)
from sqlalchemy.orm import declarative_base, sessionmaker, Session
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy import text

# ─────────────────────────────────────────────
# CONNECTION SETUP
# ─────────────────────────────────────────────
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://postgres:yash1234@localhost:5432/stylized_renderer"
)

# SQLite needs a special flag; PostgreSQL does not
connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(
    DATABASE_URL,
    connect_args=connect_args,
    echo=False,          # Set True to print every SQL statement (great for debugging)
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


# ─────────────────────────────────────────────
# MODEL: Render Job
# ─────────────────────────────────────────────
class Render(Base):
    """
    Tracks every render job from submission to completion.

    Table name: renders
    -------------------
    id               : UUID primary key
    task_id          : Celery task ID (used to look up status in Redis)
    user_id          : Anonymous session ID or auth user ID
    original_url     : S3 URL of the uploaded original image
    stylized_url     : S3 URL of the processed output image (NULL until done)
    status           : queued | processing | success | failed
    k_colors         : Pipeline parameter stored for audit/replay
    edge_method      : Pipeline parameter
    processing_s     : Wall-clock seconds the stylize() call took
    error_message    : If status=failed, what went wrong
    created_at       : When the job was submitted
    completed_at     : When the job finished (NULL until done)
    """
    __tablename__ = "renders"

    id             = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    task_id        = Column(String(255), unique=True, nullable=False, index=True)
    user_id        = Column(String(255), nullable=True, index=True)

    # S3 URLs (nullable until the job completes)
    original_url   = Column(Text, nullable=True)
    stylized_url   = Column(Text, nullable=True)

    # Job state
    status         = Column(String(50), default="queued", nullable=False)

    # Pipeline parameters (for audit trail & replay)
    k_colors       = Column(Integer, default=12)
    edge_method    = Column(String(20), default="canny")
    bilateral_passes = Column(Integer, default=3)

    # Metrics
    processing_s   = Column(Float, nullable=True)
    error_message  = Column(Text, nullable=True)

    # Timestamps (always store UTC!)
    created_at     = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    completed_at   = Column(DateTime, nullable=True)

    def to_dict(self) -> dict:
        """Serialize to JSON-safe dict for API responses."""
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


# ─────────────────────────────────────────────
# DB INITIALISATION
# ─────────────────────────────────────────────
def init_db():
    """Create all tables if they don't exist yet."""
    Base.metadata.create_all(bind=engine)


def get_db() -> Session:
    """
    FastAPI dependency that yields a database session.
    The session is automatically closed after the request finishes.

    Usage in a FastAPI route:
        @app.get("/renders")
        def list_renders(db: Session = Depends(get_db)):
            return db.query(Render).all()
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
