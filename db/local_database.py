import os
import json
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional


class LocalDatabaseManager:
    def __init__(self, db_path: str = None):
        self.db_path = db_path or os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "local_data.db"
        )
        self._init_db()

    def _get_conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _now(self):
        return datetime.now(timezone.utc).isoformat()

    def _init_db(self):
        conn = self._get_conn()
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS documents (
                id TEXT PRIMARY KEY,
                file_name TEXT NOT NULL,
                file_path TEXT,
                total_sections INTEGER DEFAULT 0,
                total_tables INTEGER DEFAULT 0,
                status TEXT DEFAULT 'parsed',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS document_sections (
                id TEXT PRIMARY KEY,
                document_id TEXT NOT NULL,
                section_index INTEGER NOT NULL,
                title TEXT NOT NULL,
                level INTEGER DEFAULT 3,
                content TEXT NOT NULL,
                meta_level_1 TEXT,
                meta_level_2 TEXT,
                meta_level_3 TEXT,
                meta_level_4 TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (document_id) REFERENCES documents(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS section_tables (
                id TEXT PRIMARY KEY,
                section_id TEXT NOT NULL,
                table_index INTEGER NOT NULL,
                headers TEXT DEFAULT '[]',
                rows TEXT DEFAULT '[]',
                caption TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (section_id) REFERENCES document_sections(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS section_function_parts (
                id TEXT PRIMARY KEY,
                section_id TEXT NOT NULL,
                part_index INTEGER NOT NULL,
                section_type TEXT NOT NULL,
                content TEXT NOT NULL,
                tables_json TEXT DEFAULT '[]',
                created_at TEXT NOT NULL,
                FOREIGN KEY (section_id) REFERENCES document_sections(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS analysis_tasks (
                id TEXT PRIMARY KEY,
                document_id TEXT NOT NULL,
                status TEXT DEFAULT 'pending',
                selected_part_ids TEXT DEFAULT '[]',
                iteration_count INTEGER DEFAULT 0,
                max_iterations INTEGER DEFAULT 3,
                error_message TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                completed_at TEXT,
                FOREIGN KEY (document_id) REFERENCES documents(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS test_points (
                id TEXT PRIMARY KEY,
                task_id TEXT NOT NULL,
                function_part_id TEXT NOT NULL,
                test_point_id TEXT NOT NULL,
                description TEXT NOT NULL,
                priority TEXT DEFAULT '中',
                test_type TEXT DEFAULT '规则验证',
                case_nature TEXT DEFAULT '正',
                transaction_name TEXT,
                test_case_path TEXT,
                steps TEXT DEFAULT '[]',
                expected_results TEXT DEFAULT '[]',
                format_valid INTEGER,
                format_issues TEXT,
                is_deleted INTEGER DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (task_id) REFERENCES analysis_tasks(id) ON DELETE CASCADE,
                FOREIGN KEY (function_part_id) REFERENCES section_function_parts(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS format_review_results (
                id TEXT PRIMARY KEY,
                task_id TEXT NOT NULL,
                test_point_id TEXT NOT NULL,
                field TEXT NOT NULL,
                issue TEXT NOT NULL,
                suggestion TEXT,
                reviewed_at TEXT NOT NULL,
                FOREIGN KEY (task_id) REFERENCES analysis_tasks(id) ON DELETE CASCADE,
                FOREIGN KEY (test_point_id) REFERENCES test_points(id) ON DELETE CASCADE
            );
        """)
        conn.commit()
        conn.close()

        self._migrate_analysis_tasks_selected_part_ids()
        self._migrate_test_points()

    def _migrate_analysis_tasks_selected_part_ids(self):
        """将 analysis_tasks.selected_section_ids 重命名为 selected_part_ids（兼容已存在的 SQLite 库）"""
        conn = self._get_conn()
        try:
            info = conn.execute("PRAGMA table_info(analysis_tasks)").fetchall()
            names = {row[1] for row in info}
            if "selected_section_ids" in names and "selected_part_ids" not in names:
                conn.execute(
                    "ALTER TABLE analysis_tasks RENAME COLUMN selected_section_ids TO selected_part_ids"
                )
            conn.commit()
        finally:
            conn.close()

    def _migrate_test_points(self):
        """为旧表添加新字段"""
        migrations = [
            "ALTER TABLE test_points ADD COLUMN case_nature TEXT DEFAULT '正'",
            "ALTER TABLE test_points ADD COLUMN transaction_name TEXT",
            "ALTER TABLE test_points ADD COLUMN test_case_path TEXT",
            "ALTER TABLE test_points ADD COLUMN is_deleted INTEGER DEFAULT 0",
        ]
        conn = self._get_conn()
        for sql in migrations:
            try:
                conn.execute(sql)
            except Exception:
                pass
        conn.commit()
        conn.close()

    # ==================== 文档操作 ====================

    def save_parsed_document(self, file_name: str, file_path: str, parsed_data):
        conn = self._get_conn()
        now = self._now()
        doc_id = str(uuid.uuid4())
        part_id_map = []
        try:
            conn.execute(
                "INSERT INTO documents (id, file_name, file_path, total_sections, total_tables, created_at, updated_at) VALUES (?,?,?,?,?,?,?)",
                (doc_id, file_name, file_path, len(parsed_data.sections), 0, now, now)
            )

            for i, sec in enumerate(parsed_data.sections):
                sec_id = str(uuid.uuid4())
                meta = sec.metadata
                content = sec.content
                if content and (content.strip() == "无" or len(content.strip()) < 5):
                    content = ""
                conn.execute(
                    "INSERT INTO document_sections (id, document_id, section_index, title, level, content, meta_level_1, meta_level_2, meta_level_3, meta_level_4, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (sec_id, doc_id, i, sec.title, sec.level, content,
                     meta.level_1 if meta else None,
                     meta.level_2 if meta else None,
                     meta.level_3 if meta else None,
                     meta.level_4 if meta else None,
                     now)
                )

                for t_idx, table in enumerate(sec.tables):
                    conn.execute(
                        "INSERT INTO section_tables (id, section_id, table_index, headers, rows, caption, created_at) VALUES (?,?,?,?,?,?,?)",
                        (str(uuid.uuid4()), sec_id, t_idx, json.dumps(table.headers, ensure_ascii=False),
                         json.dumps(table.rows, ensure_ascii=False), table.caption, now)
                )

                part_ids = []
                for p_idx, part in enumerate(sec.function_sections):
                    pid = str(uuid.uuid4())
                    conn.execute(
                        "INSERT INTO section_function_parts (id, section_id, part_index, section_type, content, created_at) VALUES (?,?,?,?,?,?)",
                        (pid, sec_id, p_idx, part.section_type, part.content, now)
                    )
                    part_ids.append(pid)
                part_id_map.append(part_ids)

            conn.commit()
            return doc_id, part_id_map
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def get_document(self, doc_id: str) -> Optional[Dict[str, Any]]:
        conn = self._get_conn()
        try:
            row = conn.execute("SELECT * FROM documents WHERE id = ?", (doc_id,)).fetchone()
            if not row:
                return None
            doc = dict(row)

            sec_rows = conn.execute(
                "SELECT * FROM document_sections WHERE document_id = ? ORDER BY section_index",
                (doc_id,)
            ).fetchall()

            sections = []
            for s in sec_rows:
                sec = dict(s)
                tables = conn.execute(
                    "SELECT * FROM section_tables WHERE section_id = ? ORDER BY table_index",
                    (sec["id"],)
                ).fetchall()
                sec["tables"] = [dict(t) for t in tables]

                fps = conn.execute(
                    "SELECT * FROM section_function_parts WHERE section_id = ? ORDER BY part_index",
                    (sec["id"],)
                ).fetchall()
                sec["function_sections"] = [dict(p) for p in fps]
                sections.append(sec)

            doc["sections"] = sections
            return doc
        finally:
            conn.close()

    # ==================== 任务操作 ====================

    def create_analysis_task(self, document_id: str, selected_part_ids: List[str]) -> str:
        conn = self._get_conn()
        now = self._now()
        task_id = str(uuid.uuid4())
        try:
            conn.execute(
                "INSERT INTO analysis_tasks (id, document_id, selected_part_ids, status, created_at, updated_at) VALUES (?,?,?,?,?,?)",
                (task_id, document_id, json.dumps(selected_part_ids, ensure_ascii=False), 'pending', now, now)
            )
            conn.commit()
            return task_id
        finally:
            conn.close()

    def update_task_status(self, task_id: str, status: str, error_message: str = None):
        conn = self._get_conn()
        now = self._now()
        try:
            if status == 'completed':
                conn.execute(
                    "UPDATE analysis_tasks SET status=?, error_message=?, updated_at=?, completed_at=? WHERE id=?",
                    (status, error_message, now, now, task_id)
                )
            else:
                conn.execute(
                    "UPDATE analysis_tasks SET status=?, error_message=?, updated_at=? WHERE id=?",
                    (status, error_message, now, task_id)
                )
            conn.commit()
        finally:
            conn.close()

    def get_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        conn = self._get_conn()
        try:
            row = conn.execute("SELECT * FROM analysis_tasks WHERE id = ?", (task_id,)).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def get_all_tasks(self) -> List[Dict[str, Any]]:
        conn = self._get_conn()
        try:
            rows = conn.execute("""
                SELECT at.*, d.file_name
                FROM analysis_tasks at
                LEFT JOIN documents d ON d.id = at.document_id
                ORDER BY at.created_at DESC
            """).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def get_test_point_count_by_task(self, task_id: str) -> int:
        conn = self._get_conn()
        try:
            row = conn.execute(
                "SELECT COUNT(*) FROM test_points WHERE task_id = ? AND is_deleted = FALSE",
                (task_id,)
            ).fetchone()
            return row[0] if row else 0
        finally:
            conn.close()

    # ==================== 测试点操作 ====================

    def get_analysis_results(self, task_id: str) -> List[Dict[str, Any]]:
        conn = self._get_conn()
        try:
            rows = conn.execute("""
                SELECT
                    at.id AS task_id,
                    at.status AS task_status,
                    d.file_name AS document_name,
                    COALESCE(sfp.section_type, '表格') AS source_type,
                    COALESCE(ds1.title, ds2.title, '规则汇总') AS source_section,
                    COALESCE(sfp.content, st.caption, '') AS source_content,
                    tp.id AS test_point_db_id,
                    tp.test_point_id,
                    tp.description,
                    tp.priority,
                    tp.test_type,
                    tp.case_nature,
                    tp.transaction_name,
                    tp.test_case_path,
                    tp.steps,
                    tp.expected_results,
                    tp.format_valid,
                    tp.created_at
                FROM test_points tp
                JOIN analysis_tasks at ON at.id = tp.task_id
                JOIN documents d ON d.id = at.document_id
                LEFT JOIN section_function_parts sfp ON sfp.id = tp.function_part_id
                LEFT JOIN document_sections ds1 ON ds1.id = sfp.section_id
                LEFT JOIN section_tables st ON st.id = tp.function_part_id
                LEFT JOIN document_sections ds2 ON ds2.id = st.section_id
                WHERE tp.task_id = ? AND tp.is_deleted = FALSE
                ORDER BY tp.created_at
            """, (task_id,)).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def get_all_test_points(self) -> List[Dict[str, Any]]:
        conn = self._get_conn()
        try:
            rows = conn.execute("""
                SELECT
                    tp.id AS test_point_db_id,
                    tp.test_point_id,
                    tp.description,
                    tp.priority,
                    tp.test_type,
                    tp.case_nature,
                    tp.transaction_name,
                    tp.test_case_path,
                    tp.steps,
                    tp.expected_results,
                    COALESCE(sfp.section_type, '表格') AS source_type,
                    tp.created_at
                FROM test_points tp
                LEFT JOIN section_function_parts sfp ON sfp.id = tp.function_part_id
                LEFT JOIN section_tables st ON st.id = tp.function_part_id
                WHERE tp.is_deleted = FALSE
                ORDER BY tp.created_at
            """).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def save_test_point(self, task_id: str, function_part_id: str, test_point, transaction_name: str = None, test_case_path: str = None) -> str:
        conn = self._get_conn()
        now = self._now()
        tp_id = str(uuid.uuid4())

        tp_bid = getattr(test_point, 'test_point_id', '') if hasattr(test_point, 'test_point_id') else test_point.get('test_point_id', '')
        tp_desc = getattr(test_point, 'description', '') if hasattr(test_point, 'description') else test_point.get('description', '')
        tp_prio = getattr(test_point, 'priority', '中') if hasattr(test_point, 'priority') else test_point.get('priority', '中')
        tp_type = getattr(test_point, 'test_type', '规则验证') if hasattr(test_point, 'test_type') else test_point.get('test_type', '规则验证')
        tp_case_nature = getattr(test_point, 'case_nature', '正') if hasattr(test_point, 'case_nature') else test_point.get('case_nature', '正')
        tp_steps = getattr(test_point, 'steps', []) if hasattr(test_point, 'steps') else test_point.get('steps', [])
        tp_exp = getattr(test_point, 'expected_results', []) if hasattr(test_point, 'expected_results') else test_point.get('expected_results', [])

        try:
            conn.execute(
                "INSERT INTO test_points (id, task_id, function_part_id, test_point_id, description, priority, test_type, case_nature, transaction_name, test_case_path, steps, expected_results, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (tp_id, task_id, function_part_id, tp_bid, tp_desc, tp_prio, tp_type, tp_case_nature,
                 transaction_name, test_case_path,
                 json.dumps(tp_steps, ensure_ascii=False), json.dumps(tp_exp, ensure_ascii=False), now, now)
            )
            conn.commit()
            return tp_id
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # ==================== function_part 操作 ====================

    def get_function_part(self, part_id: str) -> Optional[Dict[str, Any]]:
        conn = self._get_conn()
        try:
            row = conn.execute("""
                SELECT sfp.*, ds.title as section_title, ds.meta_level_2, ds.meta_level_3, d.file_path, d.id as doc_id
                FROM section_function_parts sfp
                JOIN document_sections ds ON ds.id = sfp.section_id
                JOIN documents d ON d.id = ds.document_id
                WHERE sfp.id = ?
            """, (part_id,)).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def get_function_parts_by_ids(self, part_ids: List[str]) -> List[Dict[str, Any]]:
        if not part_ids:
            return []
        conn = self._get_conn()
        try:
            placeholders = ','.join('?' for _ in part_ids)
            rows = conn.execute(f"""
                SELECT sfp.*, ds.title as section_title, d.file_path, d.id as doc_id
                FROM section_function_parts sfp
                JOIN document_sections ds ON ds.id = sfp.section_id
                JOIN documents d ON d.id = ds.document_id
                WHERE sfp.id IN ({placeholders})
                ORDER BY ds.section_index, sfp.part_index
            """, part_ids).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def get_section_table(self, table_id: str) -> Optional[Dict[str, Any]]:
        conn = self._get_conn()
        try:
            row = conn.execute("""
                SELECT st.*, ds.title as section_title, ds.meta_level_2, ds.meta_level_3, d.file_path, d.id as doc_id
                FROM section_tables st
                JOIN document_sections ds ON ds.id = st.section_id
                JOIN documents d ON d.id = ds.document_id
                WHERE st.id = ?
            """, (table_id,)).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def get_section_table_ids_by_doc(self, doc_id: str) -> List[str]:
        conn = self._get_conn()
        try:
            rows = conn.execute("""
                SELECT st.id
                FROM section_tables st
                JOIN document_sections ds ON ds.id = st.section_id
                WHERE ds.document_id = ?
                ORDER BY ds.section_index, st.table_index
            """, (doc_id,)).fetchall()
            return [r[0] for r in rows]
        finally:
            conn.close()

    def get_section_table_ids_by_part_ids(self, part_ids: List[str]) -> List[str]:
        if not part_ids:
            return []
        conn = self._get_conn()
        try:
            placeholders = ','.join('?' for _ in part_ids)
            rows = conn.execute(f"""
                SELECT DISTINCT st.id
                FROM section_tables st
                JOIN document_sections ds ON ds.id = st.section_id
                WHERE ds.id IN (
                    SELECT DISTINCT sfp.section_id
                    FROM section_function_parts sfp
                    WHERE sfp.id IN ({placeholders})
                )
                ORDER BY ds.section_index, st.table_index
            """, part_ids).fetchall()
            return [r[0] for r in rows]
        finally:
            conn.close()

    def update_test_point_format_status(self, test_point_id: str, is_valid: bool, issues: List[Dict] = None):
        conn = self._get_conn()
        now = self._now()
        try:
            conn.execute(
                "UPDATE test_points SET format_valid = ?, format_issues = ?, updated_at = ? WHERE id = ?",
                (1 if is_valid else 0, json.dumps(issues, ensure_ascii=False) if issues else None, now, test_point_id)
            )
            conn.commit()
        finally:
            conn.close()

    def save_format_review(self, task_id: str, test_point_id: str, issue_detail: Dict[str, Any]):
        conn = self._get_conn()
        now = self._now()
        try:
            conn.execute(
                "INSERT INTO format_review_results (id, task_id, test_point_id, field, issue, suggestion, reviewed_at) VALUES (?,?,?,?,?,?,?)",
                (str(uuid.uuid4()), task_id, test_point_id, issue_detail.get('field'), issue_detail.get('issue'), issue_detail.get('suggestion'), now)
            )
            conn.execute("UPDATE test_points SET format_valid = 0 WHERE id = ?", (test_point_id,))
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def get_test_point(self, tp_id: str) -> Optional[Dict[str, Any]]:
        conn = self._get_conn()
        try:
            row = conn.execute("SELECT * FROM test_points WHERE id = ?", (tp_id,)).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()
