"""PostgreSQL document / section queries; one connection per call (psycopg2 %s only)."""
from typing import Any, Callable, Dict, List, Optional

from psycopg2.extras import RealDictCursor


class DocumentRepository:
    def __init__(self, get_connection: Callable[[], Any]):
        self._get_connection = get_connection

    def get_function_part(self, part_id: str) -> Optional[Dict[str, Any]]:
        """获取需求片段详情"""
        conn = self._get_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        try:
            cur.execute(
                """
                SELECT sfp.*, ds.title as section_title, d.file_path, d.id as doc_id
                FROM section_function_parts sfp
                JOIN document_sections ds ON ds.id = sfp.section_id
                JOIN documents d ON d.id = ds.document_id
                WHERE sfp.id = %s
            """,
                (part_id,),
            )
            return cur.fetchone()
        finally:
            cur.close()
            conn.close()

    def get_section_table(self, table_id: str) -> Optional[Dict[str, Any]]:
        conn = self._get_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        try:
            cur.execute(
                """
                SELECT st.*, ds.title as section_title, ds.meta_level_2, ds.meta_level_3, d.file_path, d.id as doc_id
                FROM section_tables st
                JOIN document_sections ds ON ds.id = st.section_id
                JOIN documents d ON d.id = ds.document_id
                WHERE st.id = %s
            """,
                (table_id,),
            )
            return cur.fetchone()
        finally:
            cur.close()
            conn.close()

    def get_section_table_ids_by_part_ids(self, part_ids: List[str]) -> List[str]:
        if not part_ids:
            return []
        conn = self._get_connection()
        cur = conn.cursor()
        try:
            cur.execute(
                """
                SELECT DISTINCT st.id
                FROM section_tables st
                JOIN document_sections ds ON ds.id = st.section_id
                WHERE ds.id IN (
                    SELECT DISTINCT sfp.section_id
                    FROM section_function_parts sfp
                    WHERE sfp.id IN %s
                )
                ORDER BY ds.section_index, st.table_index
            """,
                (tuple(part_ids),),
            )
            return [r[0] for r in cur.fetchall()]
        finally:
            cur.close()
            conn.close()

    def get_section_content(self, section_id: str) -> Optional[str]:
        conn = self._get_connection()
        cur = conn.cursor()
        try:
            cur.execute(
                "SELECT content FROM document_sections WHERE id = %s",
                (section_id,),
            )
            row = cur.fetchone()
            if row is None:
                return None
            return row[0]
        finally:
            cur.close()
            conn.close()
