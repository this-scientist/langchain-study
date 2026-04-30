"""Schema / migration file presence checks (Task 1)."""

import os


def test_migration_sql_file_exists():
    root = os.path.join(
        os.path.dirname(__file__),
        "..",
        "sql",
        "migrations",
        "001_selected_part_ids_and_regeneration.sql",
    )
    root = os.path.abspath(root)
    assert os.path.isfile(root), f"missing {root}"


def test_schema_sql_contains_regeneration_jobs():
    schema_path = os.path.join(os.path.dirname(__file__), "..", "sql", "schema.sql")
    schema_path = os.path.abspath(schema_path)
    with open(schema_path, encoding="utf-8") as f:
        content = f.read()
    assert "regeneration_jobs" in content
    assert "selected_part_ids" in content
