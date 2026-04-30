"""test_points persistence; full implementation deferred to Task 6+."""
from typing import Any, Dict, List, Optional


class TestPointRepository:
    """Thin repository skeleton over PostgreSQL (to be wired in later tasks)."""

    def __init__(self, get_connection: Any):
        self._get_connection = get_connection

    def list_by_task(self, task_id: str, limit: int, offset: int) -> List[Dict[str, Any]]:
        raise NotImplementedError("Task 7: list_by_task")

    def soft_delete(self, test_point_id: str) -> None:
        raise NotImplementedError("Task 7: soft_delete")

    def insert_row(self, row: Dict[str, Any]) -> str:
        raise NotImplementedError("Task 6: insert_row")
