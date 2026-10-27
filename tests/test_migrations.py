from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect


def test_migrations_upgrade_an_empty_database(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    database_path = tmp_path / "migration.sqlite"
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", f"sqlite+pysqlite:///{database_path}")

    command.upgrade(config, "head")

    engine = create_engine(f"sqlite+pysqlite:///{database_path}")
    assert set(inspect(engine).get_table_names()) == {
        "alembic_version",
        "separation_jobs",
        "songs",
        "stems",
        "tabs",
    }
    with engine.connect() as connection:
        revision = connection.exec_driver_sql(
            "SELECT version_num FROM alembic_version"
        ).scalar_one()
    assert revision == "0002_library_schema"


def test_library_migration_upgrades_from_the_baseline(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    database_path = tmp_path / "baseline.sqlite"
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", f"sqlite+pysqlite:///{database_path}")
    command.upgrade(config, "0001_baseline")

    engine = create_engine(f"sqlite+pysqlite:///{database_path}")
    assert inspect(engine).get_table_names() == ["alembic_version"]

    command.upgrade(config, "head")
    assert "songs" in inspect(engine).get_table_names()
    command.check(config)
