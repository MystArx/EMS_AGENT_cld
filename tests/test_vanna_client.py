def test_placeholder():
    assert True
"""
tests/test_vanna_client.py
Pytest unit tests for services/api/vanna_client.py
Covers:
- schema loading
- generate_sql via pluggable provider
- validation errors for forbidden SQL
- execute_sql smoke test using an in-memory SQLite engine (no external DB needed)
"""

import os
import tempfile
import json
import pytest
import pandas as pd
from sqlalchemy import create_engine, text

from services.api.sql_client import SQLClient


def test_schema_load(tmp_path, monkeypatch):
    # create a small dummy schema file and point client at it
    schema = {
        "ems-portal-service.invoices": {"columns": ["id", "status", "amount"]}
    }
    file_path = tmp_path / "schemas_from_mdl.json"
    file_path.write_text(json.dumps(schema))
    vc = SQLClient(schema_path=str(file_path))
    assert vc.schema_json is not None
    assert "ems-portal-service.invoices" in vc.schema_json


def test_generate_sql_with_custom_provider():
    def fake_provider(question, schema):
        assert "invoices" in question
        return "SELECT * FROM invoices LIMIT 10"

    vc = SQLClient(model_provider=fake_provider)
    sql = vc.generate_sql("list invoices")
    assert isinstance(sql, str)
    assert "select" in sql.lower()


def test_validate_sql_rejects_write_ops():
    vc = SQLClient(model_provider=lambda q, s: "SELECT 1")
    # direct call to validate_sql with a DROP statement
    with pytest.raises(ValueError):
        vc.validate_sql("DROP TABLE users")

    with pytest.raises(ValueError):
        vc.validate_sql("INSERT INTO users (id) VALUES (1)")

    # Missing LIMIT should raise
    with pytest.raises(ValueError):
        vc.validate_sql("SELECT * FROM invoices")

    # Limit too large
    with pytest.raises(ValueError):
        vc.validate_sql("SELECT * FROM invoices LIMIT 20000")


def test_execute_sql_with_inmemory_sqlite(tmp_path):
    """
    Use an in-memory sqlite DB for a real execution test.
    VannaClient supports db_url_override for testing.
    """
    # create sqlite file-based DB (safer than pure :memory: to allow multiple connections)
    sqlite_path = tmp_path / "test.db"
    engine = create_engine(f"sqlite:///{sqlite_path}")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE demo (id INTEGER PRIMARY KEY, name TEXT)"))
        conn.execute(text("INSERT INTO demo (name) VALUES ('alice'), ('bob')"))

    # provider that returns a safe SELECT with LIMIT
    def provider(q, s):
        return "SELECT id, name FROM demo LIMIT 10"

    vc = SQLClient(model_provider=provider, db_url_override=f"sqlite:///{sqlite_path}")
    df = vc.ask("list demo rows")
    assert isinstance(df, pd.DataFrame)
    assert len(df) == 2
    assert set(df.columns) == {"id", "name"}
