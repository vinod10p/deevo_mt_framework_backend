"""Settings load Deevobe-style `DB_*` env names."""

import os

import pytest
from pydantic import SecretStr


@pytest.fixture(autouse=True)
def clear_settings_cache() -> None:
    from mtf.shared import config as cfg

    cfg.get_settings.cache_clear()
    yield
    cfg.get_settings.cache_clear()


def test_db_server_alias(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DB_SERVER", "sql.example.test")
    monkeypatch.setenv("DB_NAME", "mydb")
    monkeypatch.setenv("DB_USER", "u")
    monkeypatch.setenv("DB_PASSWORD", "p")
    monkeypatch.delenv("DEEVO_MSSQL_SERVER", raising=False)

    from mtf.shared.config import Settings

    s = Settings()
    assert s.mssql_server == "sql.example.test"
    assert s.mssql_database == "mydb"
    assert s.mssql_user == "u"
    assert s.mssql_password == SecretStr("p")


def test_deevo_prefixed_overrides_db_star(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DB_SERVER", "from-db-server")
    monkeypatch.setenv("DEEVO_MSSQL_SERVER", "from-deevo-server")
    monkeypatch.setenv("DB_NAME", "n")
    monkeypatch.setenv("DB_USER", "u")
    monkeypatch.setenv("DB_PASSWORD", "p")

    from mtf.shared.config import Settings

    s = Settings()
    assert s.mssql_server == "from-deevo-server"


def test_minimal_url_matches_deevobe_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DB_SERVER", "s")
    monkeypatch.setenv("DB_NAME", "d")
    monkeypatch.setenv("DB_USER", "u")
    monkeypatch.setenv("DB_PASSWORD", "p")
    monkeypatch.setenv("DB_DRIVER", "ODBC Driver 17 for SQL Server")
    monkeypatch.setenv("DEEVO_MSSQL_URL_MINIMAL", "true")
    monkeypatch.setenv("DEEVO_MSSQL_TRUST_SERVER_CERTIFICATE", "false")

    from mtf.shared.config import Settings

    uri = Settings(_env_file=None).sqlalchemy_database_uri()
    assert "mssql+pyodbc://" in uri
    assert "Encrypt=" not in uri
    assert "TrustServerCertificate=" not in uri
    assert "driver=ODBC+Driver+17+for+SQL+Server" in uri
