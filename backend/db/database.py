from functools import lru_cache
from typing import Generator

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings


class DatabaseConnectionError(RuntimeError):
    pass


@lru_cache
def get_engine():
    database_url = get_settings().require_database_url()
    return create_engine(database_url, pool_pre_ping=True)


@lru_cache
def get_session_factory():
    return sessionmaker(bind=get_engine(), autoflush=False, autocommit=False, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    db = get_session_factory()()
    try:
        yield db
    finally:
        db.close()


def check_database_connection() -> None:
    try:
        with get_engine().connect() as connection:
            connection.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        raise DatabaseConnectionError(
            "Could not connect to PostgreSQL using DATABASE_URL. Verify the database exists, "
            "the user/password are correct, and PostgreSQL accepts connections."
        ) from exc


def get_connected_database_name() -> str:
    database_url = get_settings().require_database_url()
    return make_url(database_url).database or ""
