import json
import psycopg2.extras
from langchain_core.prompts import PromptTemplate
from struct_output.test_analysis_schema import (
    SinglePartAnalysisResult,
    SingleTestPointReviewResult,
)
from prompt.test_analysis.table_analysis import TABLE_ANALYSIS_PROMPT
from prompt.test_analysis.func_desc_analysis import FUNC_DESC_ANALYSIS_PROMPT
from prompt.test_analysis.business_rule_analysis import BUSINESS_RULE_ANALYSIS_PROMPT
from prompt.test_analysis.exception_analysis import EXCEPTION_ANALYSIS_PROMPT
from prompt.test_analysis.process_analysis import PROCESS_ANALYSIS_PROMPT
from prompt.test_analysis.format_review import FORMAT_REVIEW_PROMPT
from prompt.test_analysis.permission_analysis import PERMISSION_ANALYSIS_PROMPT
from prompt.test_analysis.rule_analysis import RULE_ANALYSIS_PROMPT
from state.state_list import DocState
from typing import Dict, List, Any, Optional
from db import db_manager
from services.llm_structured import invoke_structured


# --- 节点实现（顺序工作流 / 旧版片段） ---

def fetch_next_part_node(state: DocState) -> Dict:
    """获取下一个待处理的需求片段"""
    if not state.get("pending_part_ids"):
        return {"status": "completed", "current_part_id": None}

    pending_ids = state["pending_part_ids"].copy()
    next_id = pending_ids.pop(0)

    part_data = db_manager.get_function_part(next_id)
    if not part_data:
        return {"pending_part_ids": pending_ids, "status": "error", "message": f"找不到片段 ID: {next_id}"}

    return {
        "current_part_id": next_id,
        "current_part_content": part_data["content"],
        "current_part_type": part_data["section_type"],
        "pending_part_ids": pending_ids,
        "status": "analyzing",
        "progress": f"正在分析: {part_data.get('section_title', '未命名章节')}",
    }


def analysis_node(state: DocState) -> Dict:
    """通用分析节点，根据类型调用不同的提示词"""
    part_type = state.get("current_part_type")
    content = state.get("current_part_content")
    task_id = state.get("task_id")
    part_id = state.get("current_part_id")

    if not part_id or not content:
        return {"status": "error", "message": "缺失分析内容"}

    prompt_map = {
        "表格": TABLE_ANALYSIS_PROMPT,
        "功能描述": FUNC_DESC_ANALYSIS_PROMPT,
        "业务规则": BUSINESS_RULE_ANALYSIS_PROMPT,
        "操作权限": BUSINESS_RULE_ANALYSIS_PROMPT,
        "处理过程": PROCESS_ANALYSIS_PROMPT,
        "处理流程": PROCESS_ANALYSIS_PROMPT,
        "异常处理": EXCEPTION_ANALYSIS_PROMPT,
    }

    template = prompt_map.get(part_type, FUNC_DESC_ANALYSIS_PROMPT)
    prompt = PromptTemplate.from_template(template)

    format_params = {}
    if "table_data" in template:
        format_params["table_data"] = content
    elif "func_desc_content" in template:
        format_params["func_desc_content"] = content
    elif "business_rule_content" in template:
        format_params["business_rule_content"] = content
    elif "exception_content" in template:
        format_params["exception_content"] = content
    elif "process_content" in template:
        format_params["process_content"] = content
    else:
        format_params = {"content": content}

    try:
        prompt_text = prompt.format(**format_params)
        result = invoke_structured(prompt_text, SinglePartAnalysisResult)

        saved_tp_ids = []
        for tp in result.test_points:
            tp_id = db_manager.save_test_point(task_id, part_id, tp)
            saved_tp_ids.append(tp_id)

        return {"last_saved_tp_ids": saved_tp_ids}
    except Exception as e:
        print(f"分析失败: {e}")
        return {"status": "error", "message": f"分析失败: {str(e)}"}


def format_review_node(state: DocState) -> Dict:
    """格式审查节点"""
    task_id = state.get("task_id")
    tp_ids = state.get("last_saved_tp_ids", [])

    if not tp_ids:
        return {}

    prompt_tpl = PromptTemplate.from_template(FORMAT_REVIEW_PROMPT)

    all_issues = []

    for tp_id in tp_ids:
        conn = db_manager.get_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT * FROM test_points WHERE id = %s", (tp_id,))
        tp_data = cur.fetchone()
        cur.close()
        conn.close()

        if not tp_data:
            continue

        prompt_text = prompt_tpl.format(test_point=json.dumps(tp_data, ensure_ascii=False))

        try:
            review_result = invoke_structured(
                prompt_text,
                SingleTestPointReviewResult,
                temperature=0.1,
            )

            db_manager.update_test_point_format_status(
                tp_id,
                review_result.is_valid,
                [issue.model_dump() for issue in review_result.issues],
            )

            if not review_result.is_valid:
                for issue in review_result.issues:
                    db_manager.save_format_review(task_id, tp_id, issue.model_dump())
                    all_issues.append(
                        {
                            "test_point_id": tp_id,
                            "field": issue.field,
                            "issue": issue.issue,
                            "suggestion": issue.suggestion,
                        }
                    )
        except Exception as e:
            print(f"格式审查失败 (TP: {tp_id}): {e}")

    return {"format_issues": state.get("format_issues", []) + all_issues}


# --- 测试分析平台工作流（prepare / fan-out 分析） ---

def prepare_data_node(state: DocState) -> Dict:
    """预处理节点：分类表格/权限/规则，拼接规则内容（正文+功能描述+业务规则+业务流程）"""
    task_id = state.get("task_id", "")
    part_ids = state.get("selected_part_ids", [])

    table_ids = []
    permission_ids = []
    sections_data = {}

    for pid in part_ids:
        part_data = db_manager.get_function_part(pid)
        if not part_data:
            continue
        stype = part_data.get("section_type", "")
        content = part_data.get("content", "")
        section_id = part_data.get("section_id", "")
        section_title = part_data.get("section_title", "")

        if section_id not in sections_data:
            sections_data[section_id] = {
                "title": section_title,
                "content": "",
                "parts": [],
            }

        if "操作权限" in stype:
            permission_ids.append(pid)
        elif len(content) >= 10:
            sections_data[section_id]["parts"].append(
                {
                    "type": stype,
                    "content": content,
                }
            )

    conn = db_manager._get_conn() if hasattr(db_manager, "_get_conn") else db_manager.get_connection()
    try:
        for section_id in sections_data:
            row = conn.execute("SELECT content FROM document_sections WHERE id = ?", (section_id,)).fetchone()
            if row and row[0]:
                sections_data[section_id]["content"] = row[0]
    finally:
        if hasattr(db_manager, "_get_conn"):
            conn.close()

    table_ids = db_manager.get_section_table_ids_by_part_ids(part_ids)
    table_groups = _group_table_ids_by_section(table_ids)

    print(f"[DEBUG prepare] part_ids数量={len(part_ids)}, table_ids数量={len(table_ids)}, table_groups组数={len(table_groups)}")
    print(f"[DEBUG prepare] permission_ids数量={len(permission_ids)}")

    rule_combined = ""
    rule_sections = []
    for section_id, data in sections_data.items():
        if not data["parts"]:
            continue

        section_text = f"【{data['title']}】\n"
        if data["content"] and len(data["content"]) >= 5:
            section_text += f"正文：\n{data['content']}\n\n"

        for part in data["parts"]:
            section_text += f"{part['type']}：\n{part['content']}\n\n"

        rule_sections.append(section_text.strip())

    if rule_sections:
        rule_combined = "\n\n---\n\n".join(rule_sections)

    return {
        "table_part_ids": table_ids,
        "permission_part_ids": permission_ids,
        "rule_combined_content": rule_combined,
        "rule_has_content": bool(rule_combined),
        "status": "prepared",
        "progress": f"准备就绪: 表格{len(table_ids)}个(共{len(table_groups)}组), 权限{len(permission_ids)}个, 规则{'有' if rule_combined else '无'}",
        "_table_section_groups": table_groups,
    }


def _group_table_ids_by_section(table_ids: List[str]) -> List[List[str]]:
    if not table_ids:
        return []
    groups: Dict[str, List[str]] = {}
    order: List[str] = []
    for tid in table_ids:
        td = db_manager.get_section_table(tid)
        if not td:
            continue
        sid = td.get("section_id", "")
        if sid not in groups:
            groups[sid] = []
            order.append(sid)
        groups[sid].append(tid)
    return [groups[sid] for sid in order]


def single_analysis_node(state: DocState) -> Dict:
    """分析节点，处理单个表格或权限片段；表格若为组则合并一次分析"""
    task_id = state.get("task_id")
    part_id = state.get("current_part_id")
    table_group_ids = state.get("current_table_group_ids")
    rule_content = state.get("rule_combined_content", "")

    if not part_id:
        return {}

    if table_group_ids:
        all_table_lines = []
        for tid in table_group_ids:
            td = db_manager.get_section_table(tid)
            if not td:
                continue
            headers = td.get("headers", "[]")
            rows = td.get("rows", "[]")
            if isinstance(headers, str):
                headers = json.loads(headers)
            if isinstance(rows, str):
                rows = json.loads(rows)
            caption = td.get("caption") or ""
            part_lines = []
            if caption:
                part_lines.append(caption)
            part_lines.append(" | ".join(headers))
            for row in rows:
                part_lines.append(" | ".join(row))
            all_table_lines.append("\n".join(part_lines))
        section_type = "表格"
        content = "\n\n---\n\n".join(all_table_lines)
        transaction_name = ""
        level_3 = ""
        for tid in table_group_ids:
            td = db_manager.get_section_table(tid)
            if td:
                transaction_name = td.get("meta_level_2", "") or transaction_name
                level_3 = td.get("meta_level_3", "") or level_3
    else:
        part_data = db_manager.get_function_part(part_id)
        table_data = None
        if part_data is None:
            table_data = db_manager.get_section_table(part_id)
        if part_data is None and table_data is None:
            return {}

        if table_data:
            headers = table_data.get("headers", "[]")
            rows = table_data.get("rows", "[]")
            if isinstance(headers, str):
                headers = json.loads(headers)
            if isinstance(rows, str):
                rows = json.loads(rows)
            caption = table_data.get("caption", "")
            content_lines = []
            if caption:
                content_lines.append(caption)
            content_lines.append(" | ".join(headers))
            for row in rows:
                content_lines.append(" | ".join(row))
            section_type = "表格"
            content = "\n".join(content_lines)
            transaction_name = table_data.get("meta_level_2", "")
            level_3 = table_data.get("meta_level_3", "")
        else:
            section_type = part_data["section_type"]
            content = part_data["content"]
            transaction_name = part_data.get("meta_level_2", "")
            level_3 = part_data.get("meta_level_3", "")

    if section_type == "表格":
        template = TABLE_ANALYSIS_PROMPT
        format_params = {
            "table_data": content,
            "business_rules": rule_content if rule_content else "无相关业务规则",
        }
    elif "操作权限" in section_type:
        template = PERMISSION_ANALYSIS_PROMPT
        format_params = {
            "permission_content": content,
            "business_rules": rule_content if rule_content else "无相关业务规则",
        }
    else:
        return {}

    try:
        prompt_text = PromptTemplate.from_template(template).format(**format_params)
        result = invoke_structured(prompt_text, SinglePartAnalysisResult)

        save_part_id = table_group_ids[0] if table_group_ids else part_id
        test_case_path = f"{transaction_name}\\{level_3}" if transaction_name else ""

        print(f"[DEBUG] section_type={section_type}, original save_part_id={save_part_id}")

        if section_type == "表格":
            sample_tid = table_group_ids[0] if table_group_ids else part_id
            print(f"[DEBUG] 表格处理: sample_tid={sample_tid}, table_group_ids={table_group_ids}")
            sample_table = db_manager.get_section_table(sample_tid)
            if sample_table:
                section_id = sample_table.get("section_id", "")
                print(f"[DEBUG] 获取到 section_id={section_id}")
                if section_id:
                    conn = db_manager._get_conn() if hasattr(db_manager, "_get_conn") else db_manager.get_connection()
                    try:
                        existing_part = conn.execute(
                            "SELECT id FROM section_function_parts WHERE section_id = ? LIMIT 1",
                            (section_id,),
                        ).fetchone()
                        print(f"[DEBUG] 查询现有 part: {existing_part}")
                        if existing_part:
                            save_part_id = existing_part[0]
                            print(f"[DEBUG] 使用现有 part_id: {save_part_id}")
                        else:
                            import uuid

                            new_part_id = str(uuid.uuid4())
                            print(f"[DEBUG] 创建新 part: {new_part_id}, section_id={section_id}")
                            conn.execute(
                                "INSERT INTO section_function_parts (id, section_id, part_index, section_type, content, created_at) VALUES (?,?,?,?,?,?)",
                                (new_part_id, section_id, 0, "表格", content[:500], db_manager._now()),
                            )
                            conn.commit()
                            save_part_id = new_part_id
                            print(f"[DEBUG] 新 part 创建成功: {save_part_id}")
                    finally:
                        if hasattr(db_manager, "_get_conn"):
                            conn.close()

        print(f"[DEBUG] 最终 save_part_id={save_part_id}, 测试点数量={len(result.test_points)}")

        for tp in result.test_points:
            db_manager.save_test_point(task_id, save_part_id, tp, transaction_name, test_case_path)

        return {}
    except Exception as e:
        import traceback

        print(f"分析失败: {e}")
        traceback.print_exc()
        return {}


def rule_analysis_node(state: DocState) -> Dict:
    """规则分析节点，将所有非表格非权限规则类内容拼接后一次性分析"""
    rule_content = state.get("rule_combined_content", "")
    task_id = state.get("task_id")

    if not rule_content:
        return {}

    try:
        prompt_text = RULE_ANALYSIS_PROMPT.format(rule_content=rule_content)
        result = invoke_structured(prompt_text, SinglePartAnalysisResult)

        conn = db_manager._get_conn() if hasattr(db_manager, "_get_conn") else db_manager.get_connection()
        doc_row = conn.execute("SELECT document_id FROM analysis_tasks WHERE id = ?", (task_id,)).fetchone()
        first_part_id = None
        transaction_name = ""
        if doc_row:
            doc_id = doc_row[0]
            part_row = conn.execute(
                """
                SELECT sfp.id, ds.meta_level_2
                FROM section_function_parts sfp
                JOIN document_sections ds ON ds.id = sfp.section_id
                WHERE ds.document_id = ?
                  AND sfp.section_type NOT IN ('表格', '操作权限')
                  AND LENGTH(sfp.content) >= 10
                ORDER BY ds.section_index, sfp.part_index
                LIMIT 1
            """,
                (doc_id,),
            ).fetchone()
            if part_row:
                first_part_id = part_row[0]
                transaction_name = part_row[1] or ""
        if hasattr(db_manager, "_get_conn"):
            conn.close()

        level_3 = ""
        test_case_path = f"{transaction_name}\\{level_3}" if transaction_name else ""

        if first_part_id:
            for tp in result.test_points:
                db_manager.save_test_point(task_id, first_part_id, tp, transaction_name, test_case_path)

        return {}
    except Exception as e:
        print(f"规则分析失败: {e}")
        return {}
