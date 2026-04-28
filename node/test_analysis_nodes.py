import os
import json
import re
import time
import psycopg2.extras
from langchain_openai import ChatOpenAI
from langchain_core.prompts import PromptTemplate
from pydantic import BaseModel
from struct_output.test_analysis_schema import (
    SinglePartAnalysisResult, SingleTestPointReviewResult, FormatReviewIssue
)
from prompt.test_analysis import (
    TABLE_ANALYSIS_PROMPT, FUNC_DESC_ANALYSIS_PROMPT,
    BUSINESS_RULE_ANALYSIS_PROMPT, EXCEPTION_ANALYSIS_PROMPT,
    PROCESS_ANALYSIS_PROMPT, FORMAT_REVIEW_PROMPT
)
from state.state_list import DocState
from typing import Dict, List, Any, Optional
from db.database import db_manager

GLM_API_KEY = os.environ["GLM_API_KEY"]
GLM_BASE_URL = os.environ["GLM_BASE_URL"]
GLM_MODEL = os.environ["GLM_MODEL"]

def _get_llm(temperature: float = 0.3) -> ChatOpenAI:
    return ChatOpenAI(
        model=GLM_MODEL,
        temperature=temperature,
        api_key=GLM_API_KEY,
        base_url=GLM_BASE_URL,
    )

def _invoke_structured(llm: ChatOpenAI, prompt_text: str, output_cls) -> BaseModel:
    last_error = None
    for attempt in range(3):
        try:
            raw = llm.invoke(prompt_text)
            content = raw.content.strip() if raw.content else ""
            if not content:
                raise ValueError("LLM 返回空内容")

            content = re.sub(r'^```(?:markdown|json|)\s*', '', content)
            content = re.sub(r'\s*```$', '', content)
            content = content.strip()
            data = json.loads(content)
            return output_cls.model_validate(data)
        except Exception as e:
            last_error = e
            if attempt < 2:
                time.sleep(1 * (attempt + 1))
                continue
            raise last_error

# --- 节点实现 ---

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
        "progress": f"正在分析: {part_data.get('section_title', '未命名章节')}"
    }

def analysis_node(state: DocState) -> Dict:
    """通用分析节点，根据类型调用不同的提示词"""
    part_type = state.get("current_part_type")
    content = state.get("current_part_content")
    task_id = state.get("task_id")
    part_id = state.get("current_part_id")
    
    if not part_id or not content:
        return {"status": "error", "message": "缺失分析内容"}

    # 映射提示词模板
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
    
    # 根据模板参数进行格式化
    # 这里的参数名需要根据 prompt/test_analysis.py 中的实际定义来调整
    # 假设通用的参数名为 content 或具体类型名
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
        # 兜底
        format_params = {"content": content}

    try:
        prompt_text = prompt.format(**format_params)
        result = _invoke_structured(_get_llm(0.3), prompt_text, SinglePartAnalysisResult)
        
        # 保存结果到数据库
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

    llm = _get_llm(0.1) # 审查建议使用低温度
    prompt_tpl = PromptTemplate.from_template(FORMAT_REVIEW_PROMPT)
    
    all_issues = []
    
    # 批量查询刚刚保存的测试点数据进行审查
    # 为了简化，这里直接针对每个 tp_id 进行 LLM 审查
    # 实际项目中可能需要更高效的批量审查方式
    for tp_id in tp_ids:
        # 获取测试点完整数据 (可以从 DB 查，或者在 analysis_node 中传递)
        # 这里为了演示，假设我们有一个简单的查询方法
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
            review_result = _invoke_structured(llm, prompt_text, SingleTestPointReviewResult)
            
            # 更新 DB 中的审查状态
            db_manager.update_test_point_format_status(
                tp_id, 
                review_result.is_valid, 
                [issue.model_dump() for issue in review_result.issues]
            )
            
            # 如果不合格，记录到 format_review_results 表
            if not review_result.is_valid:
                for issue in review_result.issues:
                    db_manager.save_format_review(task_id, tp_id, issue.model_dump())
                    all_issues.append({
                        "test_point_id": tp_id,
                        "field": issue.field,
                        "issue": issue.issue,
                        "suggestion": issue.suggestion
                    })
        except Exception as e:
            print(f"格式审查失败 (TP: {tp_id}): {e}")
            
    return {"format_issues": state.get("format_issues", []) + all_issues}
