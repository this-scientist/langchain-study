"""regeneration_jobs persistence (PostgreSQL, %s placeholders)."""
import json
import uuid
from typing import Any, Callable, Dict, Optional

from psycopg2.extras import RealDictCursor


class RegenerationJobRepository:
    def __init__(self, get_connection: Callable[[], Any]):
        self._get_connection = get_connection

    def create_job(self, task_id: str, payload: Dict[str, Any]) -> str:
        job_id = str(uuid.uuid4())
        conn = self._get_connection()
        cur = conn.cursor()
        try:
            cur.execute(
                """
                INSERT INTO regeneration_jobs (id, task_id, status, payload)
                VALUES (%s, %s, 'pending', %s::jsonb)
                """,
                (job_id, task_id, json.dumps(payload)),
            )
            conn.commit()
            return job_id
        except Exception:
            conn.rollback()
            raise
        finally:
            cur.close()
            conn.close()

    def get_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        conn = self._get_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        try:
            cur.execute("SELECT * FROM regeneration_jobs WHERE id = %s", (job_id,))
            row = cur.fetchone()
            return dict(row) if row else None
        finally:
            cur.close()
            conn.close()

    def update_progress(self, job_id: str, progress: Dict[str, Any]) -> None:
        conn = self._get_connection()
        cur = conn.cursor()
        try:
            cur.execute(
                """
                UPDATE regeneration_jobs
                SET progress = %s::jsonb, updated_at = now()
                WHERE id = %s
                """,
                (json.dumps(progress), job_id),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            cur.close()
            conn.close()

    def mark_running(self, job_id: str) -> bool:
        """pending → running; returns True if a row was updated."""
        conn = self._get_connection()
        cur = conn.cursor()
        try:
            cur.execute(
                """
                UPDATE regeneration_jobs
                SET status = 'running', started_at = now(), updated_at = now()
                WHERE id = %s AND status = 'pending'
                """,
                (job_id,),
            )
            n = cur.rowcount
            conn.commit()
            return n > 0
        except Exception:
            conn.rollback()
            raise
        finally:
            cur.close()
            conn.close()

    def mark_completed(self, job_id: str) -> None:
        conn = self._get_connection()
        cur = conn.cursor()
        try:
            cur.execute(
                """
                UPDATE regeneration_jobs
                SET status = 'completed', completed_at = now(), updated_at = now()
                WHERE id = %s
                """,
                (job_id,),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            cur.close()
            conn.close()

    def mark_failed(self, job_id: str, error_message: str) -> None:
        conn = self._get_connection()
        cur = conn.cursor()
        try:
            cur.execute(
                """
                UPDATE regeneration_jobs
                SET status = 'failed', error_message = %s, completed_at = now(), updated_at = now()
                WHERE id = %s
                """,
                (error_message, job_id),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            cur.close()
            conn.close()
