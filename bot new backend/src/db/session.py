from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.core.config import get_settings
from src.db.base import Base

settings = get_settings()

engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=10,
)

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,  # ✅ prevents DetachedInstanceError patterns
    bind=engine,
)
