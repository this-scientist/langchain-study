"""Task repository SQL contract tests (mocked; no live PostgreSQL)."""
import json
from unittest.mock import MagicMock, patch

from db.database import DatabaseManager


def test_create_analysis_task_sql_uses_selected_part_ids_not_section_ids():
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_conn.cursor.return_value = mock_cursor

    with patch("db.database.psycopg2.connect", return_value=mock_conn):
        dm = DatabaseManager()
        doc_id = "00000000-0000-0000-0000-000000000001"
        parts = [
            "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
            "11111111-2222-3333-4444-555555555555",
        ]
        dm.create_analysis_task(doc_id, parts)

    mock_cursor.execute.assert_called_once()
    sql, params = mock_cursor.execute.call_args[0]
    assert "selected_part_ids" in sql
    assert "selected_section_ids" not in sql
    assert params[1] == doc_id
    assert json.loads(params[2]) == parts
    assert params[3] == "pending"


def test_create_analysis_task_empty_parts_json_and_status():
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_conn.cursor.return_value = mock_cursor

    with patch("db.database.psycopg2.connect", return_value=mock_conn):
        dm = DatabaseManager()
        dm.create_analysis_task("doc-uuid", [])

    _sql, params = mock_cursor.execute.call_args[0]
    assert params[2] == "[]"
    assert params[3] == "pending"
