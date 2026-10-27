"""SQLAlchemy engine and session construction."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine, event, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class Base(DeclarativeBase):
    pass


def create_database_engine(database_url: str, *, echo: bool = False) -> Engine:
    """Create a SQLAlchemy engine without opening a connection eagerly."""

    if not database_url.strip():
        raise ValueError("database_url must not be blank")
    engine = create_engine(database_url, echo=echo, pool_pre_ping=True)
    if engine.dialect.name == "sqlite":
        event.listen(
            engine,
            "connect",
            lambda connection, _record: connection.execute("PRAGMA foreign_keys=ON"),
        )
    return engine


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    """Create sessions with explicit transaction ownership."""

    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def check_database(engine: Engine) -> bool:
    """Run a minimal query to verify database connectivity."""

    with engine.connect() as connection:
        return connection.execute(text("SELECT 1")).scalar_one() == 1


@contextmanager
def session_scope(factory: sessionmaker[Session]) -> Iterator[Session]:
    """Yield a session and commit or roll back its transaction."""

    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
