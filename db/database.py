import os
import json
import psycopg2
from psycopg2.extras import RealDictCursor, execute_values
from typing import Dict, List, Any, Optional
import uuid

class DatabaseManager:
    def __init__(self):
        self.host = os.getenv("DB_HOST", "8.138.101.86")
        self.port = os.getenv("DB_PORT", "5432")
        self.dbname = os.getenv("DB_NAME", "langchain_db")
        self.user = os.getenv("DB_USER", "postgres")
        self.password = os.getenv("DB_PASSWORD", "!yyf19981122")

    def get_connection(self):
        return psycopg2.connect(
            host=self.host,
            port=self.port,
            dbname=self.dbname,
            user=self.user,
            password=self.password
        )

    def save_parsed_document(self, file_name: str, file_path: str, parsed_data: Any) -> str:
        """保存解析后的文档到数据库"""
        conn = self.get_connection()
        cur = conn.cursor()
        try:
            doc_id = str(uuid.uuid4())
            # 1. 插入 documents 表
            cur.execute(
                "INSERT INTO documents (id, file_name, file_path, total_sections, total_tables) VALUES (%s, %s, %s, %s, %s)",
                (doc_id, file_name, file_path, len(parsed_data.sections), 0)
            )

            # 2. 插入 document_sections 表
            for i, sec in enumerate(parsed_data.sections):
                sec_id = str(uuid.uuid4())
                cur.execute(
                    """INSERT INTO document_sections 
                       (id, document_id, section_index, title, level, content, meta_level_1, meta_level_2, meta_level_3, meta_level_4)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                    (sec_id, doc_id, i, sec.title, sec.level, sec.content, 
                     sec.metadata.level_1, sec.metadata.level_2, sec.metadata.level_3, sec.metadata.level_4)
                )

                # 3. 插入 section_tables 表
                for t_idx, table in enumerate(sec.tables):
                    cur.execute(
                        "INSERT INTO section_tables (section_id, table_index, headers, rows, caption) VALUES (%s, %s, %s, %s, %s)",
                        (sec_id, t_idx, json.dumps(table.headers), json.dumps(table.rows), table.caption)
                    )

                # 4. 插入 section_function_parts 表
                for p_idx, part in enumerate(sec.function_sections):
                    cur.execute(
                        "INSERT INTO section_function_parts (section_id, part_index, section_type, content, tables_json) VALUES (%s, %s, %s, %s, %s)",
                        (sec_id, p_idx, part.section_type, part.content, json.dumps([])) # tables_json 暂存为空
                    )

            conn.commit()
            return doc_id
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            cur.close()
            conn.close()

    def create_analysis_task(self, document_id: str, selected_sections: List[int]) -> str:
        """创建分析任务"""
        conn = self.get_connection()
        cur = conn.cursor()
        try:
            task_id = str(uuid.uuid4())
            cur.execute(
                "INSERT INTO analysis_tasks (id, document_id, selected_section_ids, status) VALUES (%s, %s, %s, %s)",
                (task_id, document_id, json.dumps(selected_sections), 'running')
            )
            conn.commit()
            return task_id
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            cur.close()
            conn.close()

    def update_task_status(self, task_id: str, status: str, error_message: str = None, progress: str = None):
        """更新任务状态"""
        conn = self.get_connection()
        cur = conn.cursor()
        try:
            updates = ["status = %s", "updated_at = now()"]
            params = [status]
            
            if error_message is not None:
                updates.append("error_message = %s")
                params.append(error_message)
            
            if progress is not None:
                # 假设我们在 analysis_tasks 表中添加了 progress 字段，或者复用 error_message 存储进度
                # 目前 schema 中没有 progress 字段，我们先只更新状态和错误信息
                pass
                
            params.append(task_id)
            query = f"UPDATE analysis_tasks SET {', '.join(updates)} WHERE id = %s"
            cur.execute(query, tuple(params))
            conn.commit()
        finally:
            cur.close()
            conn.close()

    def get_document(self, doc_id: str) -> Optional[Dict[str, Any]]:
        """获取文档详情及其章节"""
        conn = self.get_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        try:
            # 1. 获取文档基本信息
            cur.execute("SELECT * FROM documents WHERE id = %s", (doc_id,))
            doc = cur.fetchone()
            if not doc:
                return None
            
            # 2. 获取章节信息
            cur.execute("""
                SELECT * FROM document_sections 
                WHERE document_id = %s 
                ORDER BY section_index ASC
            """, (doc_id,))
            sections = cur.fetchall()
            
            # 3. 为每个章节获取表格和功能部分
            for sec in sections:
                cur.execute("SELECT * FROM section_tables WHERE section_id = %s ORDER BY table_index ASC", (sec['id'],))
                sec['tables'] = cur.fetchall()
                
                cur.execute("SELECT * FROM section_function_parts WHERE section_id = %s ORDER BY part_index ASC", (sec['id'],))
                sec['function_sections'] = cur.fetchall()
            
            doc['sections'] = sections
            return doc
        finally:
            cur.close()
            conn.close()

    def get_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        """获取任务详情"""
        conn = self.get_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        try:
            cur.execute("SELECT * FROM analysis_tasks WHERE id = %s", (task_id,))
            return cur.fetchone()
        finally:
            cur.close()
            conn.close()

    def get_analysis_results(self, task_id: str) -> List[Dict[str, Any]]:
        """获取任务的所有测试点结果"""
        conn = self.get_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        try:
            # 直接从视图查询，获取关联了原文信息的测试点
            cur.execute("SELECT * FROM v_task_test_points WHERE task_id = %s ORDER BY created_at ASC", (task_id,))
            return cur.fetchall()
        finally:
            cur.close()
            conn.close()

    def save_test_point(self, task_id: str, function_part_id: str, test_point: Dict[str, Any]) -> str:
        """保存单个测试点"""
        conn = self.get_connection()
        cur = conn.cursor()
        try:
            tp_id = str(uuid.uuid4())
            
            # 处理 Pydantic 对象或字典
            tp_bid = getattr(test_point, 'test_point_id', '') if hasattr(test_point, 'test_point_id') else test_point.get('test_point_id', '')
            tp_desc = getattr(test_point, 'description', '') if hasattr(test_point, 'description') else test_point.get('description', '')
            tp_prio = getattr(test_point, 'priority', '中') if hasattr(test_point, 'priority') else test_point.get('priority', '中')
            tp_type = getattr(test_point, 'test_type', '功能测试') if hasattr(test_point, 'test_type') else test_point.get('test_type', '功能测试')
            tp_steps = getattr(test_point, 'steps', []) if hasattr(test_point, 'steps') else test_point.get('steps', [])
            tp_exp = getattr(test_point, 'expected_results', []) if hasattr(test_point, 'expected_results') else test_point.get('expected_results', [])

            cur.execute(
                """INSERT INTO test_points 
                   (id, task_id, function_part_id, test_point_id, description, priority, test_type, steps, expected_results)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (tp_id, task_id, function_part_id, tp_bid, tp_desc, tp_prio, tp_type, 
                 json.dumps(tp_steps), json.dumps(tp_exp))
            )
            conn.commit()
            return tp_id
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            cur.close()
            conn.close()

    def save_format_review(self, task_id: str, test_point_id: str, issue_detail: Dict[str, Any]):
        """保存格式审查结果"""
        conn = self.get_connection()
        cur = conn.cursor()
        try:
            # issue_detail: {field: "steps", issue: "...", suggestion: "..."}
            cur.execute(
                """INSERT INTO format_review_results 
                   (task_id, test_point_id, field, issue, suggestion)
                   VALUES (%s, %s, %s, %s, %s)""",
                (task_id, test_point_id, issue_detail.get('field'), issue_detail.get('issue'), issue_detail.get('suggestion'))
            )
            # 同时更新 test_points 表的审查状态
            cur.execute(
                "UPDATE test_points SET format_valid = FALSE WHERE id = %s",
                (test_point_id,)
            )
            conn.commit()
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            cur.close()
            conn.close()

    def update_test_point_format_status(self, test_point_id: str, is_valid: bool, issues: List[Dict[str, Any]] = None):
        """更新测试点的格式审查状态"""
        conn = self.get_connection()
        cur = conn.cursor()
        try:
            cur.execute(
                "UPDATE test_points SET format_valid = %s, format_issues = %s, updated_at = now() WHERE id = %s",
                (is_valid, json.dumps(issues) if issues else None, test_point_id)
            )
            conn.commit()
        finally:
            cur.close()
            conn.close()

    def get_function_part(self, part_id: str) -> Optional[Dict[str, Any]]:
        """获取需求片段详情"""
        conn = self.get_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        try:
            cur.execute("""
                SELECT sfp.*, ds.title as section_title, d.file_path, d.id as doc_id
                FROM section_function_parts sfp
                JOIN document_sections ds ON ds.id = sfp.section_id
                JOIN documents d ON d.id = ds.document_id
                WHERE sfp.id = %s
            """, (part_id,))
            return cur.fetchone()
        finally:
            cur.close()
            conn.close()

    def get_function_parts_by_ids(self, part_ids: List[str]) -> List[Dict[str, Any]]:
        """批量获取需求片段详情"""
        if not part_ids:
            return []
        conn = self.get_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        try:
            cur.execute("""
                SELECT sfp.*, ds.title as section_title, d.file_path, d.id as doc_id
                FROM section_function_parts sfp
                JOIN document_sections ds ON ds.id = sfp.section_id
                JOIN documents d ON d.id = ds.document_id
                WHERE sfp.id IN %s
                ORDER BY ds.section_index ASC, sfp.part_index ASC
            """, (tuple(part_ids),))
            return cur.fetchall()
        finally:
            cur.close()
            conn.close()

db_manager = DatabaseManager()
