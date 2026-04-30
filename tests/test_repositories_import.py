"""Repository package smoke tests (mocked PostgreSQL connections)."""
from unittest.mock import MagicMock

from db.repositories import DocumentRepository


def test_import_document_repository_from_package():
    assert DocumentRepository is not None


def test_get_section_content_uses_placeholder_and_document_sections_sql():
    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = ("section body",)
    mock_conn = MagicMock()
    mock_conn.cursor.return_value = mock_cursor

    repo = DocumentRepository(lambda: mock_conn)
    assert repo.get_section_content("x") == "section body"

    mock_cursor.execute.assert_called_once()
    sql, params = mock_cursor.execute.call_args[0]
    assert "document_sections" in sql.replace("\n", " ")
    assert "%s" in sql
    assert params == ("x",)
    mock_cursor.close.assert_called_once()
    mock_conn.close.assert_called_once()
