"""test_points persistence (PostgreSQL)."""
from typing import Any, Callable, Dict, List, Optional

from psycopg2.extras import RealDictCursor


class TestPointRepository:
    def __init__(self, get_connection: Callable[[], Any]):
        self._get_connection = get_connection

    def list_by_task(
        self, task_id: str, limit: int = 100, offset: int = 0
    ) -> List[Dict[str, Any]]:
        conn = self._get_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        try:
            cur.execute(
                """
                SELECT
                    tp.*,
                    sfp.section_type AS source_type,
                    ds.title AS source_section_title
                FROM test_points tp
                JOIN section_function_parts sfp ON sfp.id = tp.function_part_id
                JOIN document_sections ds ON ds.id = sfp.section_id
                WHERE tp.task_id = %s AND tp.is_deleted = FALSE
                ORDER BY tp.created_at ASC
                LIMIT %s OFFSET %s
                """,
                (task_id, limit, offset),
            )
            rows = cur.fetchall()
            return [dict(r) for r in rows]
        finally:
            cur.close()
            conn.close()

    def soft_delete(self, test_point_id: str, task_id: str) -> int:
        conn = self._get_connection()
        cur = conn.cursor()
        try:
            cur.execute(
                """
                UPDATE test_points
                SET is_deleted = TRUE, updated_at = now()
                WHERE id = %s AND task_id = %s AND is_deleted = FALSE
                """,
                (test_point_id, task_id),
            )
            n = cur.rowcount
            conn.commit()
            return n
        except Exception:
            conn.rollback()
            raise
        finally:
            cur.close()
            conn.close()

    def get_active_for_task(self, test_point_id: str, task_id: str) -> Optional[Dict[str, Any]]:
        conn = self._get_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        try:
            cur.execute(
                """
                SELECT tp.*, sfp.content AS part_content, sfp.section_type AS part_section_type
                FROM test_points tp
                JOIN section_function_parts sfp ON sfp.id = tp.function_part_id
                WHERE tp.id = %s AND tp.task_id = %s AND tp.is_deleted = FALSE
                """,
                (test_point_id, task_id),
            )
            row = cur.fetchone()
            return dict(row) if row else None
        finally:
            cur.close()
            conn.close()
