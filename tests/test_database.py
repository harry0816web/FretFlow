import pytest
from sqlalchemy import text

from fretflow.database import (
    check_database,
    create_database_engine,
    create_session_factory,
    session_scope,
)


def test_database_helpers_connect_and_commit():
    engine = create_database_engine("sqlite+pysqlite:///:memory:")
    factory = create_session_factory(engine)
    assert check_database(engine)

    with session_scope(factory) as session:
        assert session.execute(text("SELECT 1")).scalar_one() == 1


def test_create_database_engine_rejects_blank_url():
    with pytest.raises(ValueError):
        create_database_engine(" ")


def test_session_scope_rolls_back_errors():
    engine = create_database_engine("sqlite+pysqlite:///:memory:")
    factory = create_session_factory(engine)

    with pytest.raises(RuntimeError):
        with session_scope(factory):
            raise RuntimeError("boom")
