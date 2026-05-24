"""SQLAlchemy engine, session factory, and declarative Base."""

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from mtf.shared.config import get_settings


class Base(DeclarativeBase):
    """Subclass per entity in domain models.py modules."""
    pass


settings = get_settings()

engine = create_engine(
    settings.sqlalchemy_database_uri(),
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
    pool_timeout=30,
    echo=settings.debug,    # logs SQL queries in development
)

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
)

