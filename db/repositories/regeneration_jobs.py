"""regeneration_jobs persistence; full implementation deferred to Task 6+."""
from typing import Any, Dict, Optional


class RegenerationJobRepository:
    """Thin repository skeleton over PostgreSQL (to be wired in later tasks)."""

    def __init__(self, get_connection: Any):
        self._get_connection = get_connection

    def create_job(self, task_id: str, payload: Dict[str, Any]) -> str:
        raise NotImplementedError("Task 6: create_job — INSERT regeneration_jobs with %s placeholders")

    def get_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        raise NotImplementedError("Task 6: get_job — SELECT FROM regeneration_jobs WHERE id = %s")

    def update_progress(self, job_id: str, progress: Dict[str, Any]) -> None:
        raise NotImplementedError("Task 6: update_progress")

    def mark_running(self, job_id: str) -> bool:
        raise NotImplementedError("Task 6: mark_running")

    def mark_completed(self, job_id: str) -> None:
        raise NotImplementedError("Task 6: mark_completed")

    def mark_failed(self, job_id: str, error_message: str) -> None:
        raise NotImplementedError("Task 6: mark_failed")
