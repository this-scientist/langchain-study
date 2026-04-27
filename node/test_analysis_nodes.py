import os
import json
import re
from langchain_openai import ChatOpenAI
from langchain_core.prompts import PromptTemplate
from langgraph.types import interrupt
from pydantic import BaseModel
from struct_output.output_list import (
    TestPoint, ApprovalFeedback,
    DocSectionWithMetadata, TableData,
    UserReviewStatus,
    AggregatedTestAnalysis, SourceFragmentWithPoints, AggregatedTestPoint,
)
from struct_output.test_analysis_schema import (
    TableAnalysisResult, FuncDescAnalysisResult,
    BusinessRuleAnalysisResult, ExceptionAnalysisResult,
    ProcessAnalysisResult, ReviewResult,
)
from prompt.test_analysis import (
    TABLE_ANALYSIS_PROMPT, FUNC_DESC_ANALYSIS_PROMPT,
    BUSINESS_RULE_ANALYSIS_PROMPT, EXCEPTION_ANALYSIS_PROMPT,
    PROCESS_ANALYSIS_PROMPT, REVIEW_AGENT_PROMPT,
)
from state.state_list import DocState
from typing import Dict, List, Tuple

SECTION_TYPE_MAP = {
    "功能描述": "func_desc",
    "业务规则": "business_rule",
    "操作权限": "business_rule",
    "处理过程": "process",
    "处理流程": "process",
    "异常处理": "exception",
}

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
    raw = llm.invoke(prompt_text)
    content = raw.content.strip()
    content = re.sub(r'^```(?:markdown|json|)\s*', '', content)
    content = re.sub(r'\s*```$', '', content)
    content = content.strip()
    data = json.loads(content)
    return output_cls.model_validate(data)


def _get_selected_sections(state: DocState) -> List[DocSectionWithMetadata]:
    sections = state.get("parsed_data")
    if not sections or not sections.sections:
        return []
    indices = state.get("selected_section_indices", [])
    if not indices:
        return sections.sections
    return [sections.sections[i] for i in indices if i < len(sections.sections)]


def _collect_table_data(sections: List[DocSectionWithMetadata]) -> List[Tuple[str, TableData]]:
    tables = []
    for sec in sections:
        for t in sec.tables:
            tables.append((sec.title, t))
        for fs in sec.function_sections:
            for t in fs.tables:
                tables.append((f"{sec.title} - {fs.section_type}", t))
    return tables


def _collect_function_sections(sections: List[DocSectionWithMetadata], section_type: str) -> List[Tuple[str, str, str]]:
    results = []
    for sec in sections:
        for fs in sec.function_sections:
            mapped = SECTION_TYPE_MAP.get(fs.section_type, "")
            if mapped == section_type:
                results.append((sec.title, fs.section_type, fs.content))
    return results


def _format_table_data(tables: List[Tuple[str, TableData]]) -> str:
    lines = []
    for i, (section_title, table) in enumerate(tables, 1):
        lines.append(f"\n【表格{i}】来源章节: {section_title}")
        lines.append(f"列标题: {', '.join(table.headers)}")
        for j, row in enumerate(table.rows, 1):
            lines.append(f"  行{j}: {', '.join(row)}")
    return "\n".join(lines)


def _format_section_content(items: List[Tuple[str, str, str]], max_len: int = 500) -> str:
    lines = []
    for section_title, stype, content in items:
        lines.append(f"\n【{section_title} - {stype}】\n{content[:max_len]}")
    return "\n".join(lines)




def _build_aggregated_analysis(
    result,
    source_type: str,
    section_title: str,
) -> AggregatedTestAnalysis:
    fragments_map = {}
    for sf in result.source_fragments:
        fragments_map[sf.index] = SourceFragmentWithPoints(
            index=sf.index,
            section_title=sf.section_title,
            content=sf.content,
            test_points=[],
        )

    for tp in result.test_points:
        agg_tp = AggregatedTestPoint(
            test_point_id=tp.test_point_id,
            description=tp.description,
            source_fragment_index=tp.source_fragment_index,
            priority=tp.priority,
            test_type=tp.test_type,
            source_type=source_type,
            steps=getattr(tp, 'steps', []),
            expected_results=getattr(tp, 'expected_results', []),
        )
        if tp.source_fragment_index in fragments_map:
            fragments_map[tp.source_fragment_index].test_points.append(agg_tp)

    fragments = sorted(fragments_map.values(), key=lambda f: f.index)
    return AggregatedTestAnalysis(
        fragments=fragments,
        total_test_points=len(result.test_points),
        total_fragments=len(fragments),
        coverage_analysis=result.coverage_analysis,
    )


def _merge_aggregated_analyses(analyses: List[AggregatedTestAnalysis]) -> AggregatedTestAnalysis:
    all_fragments = []
    seen_indices = set()
    total_points = 0

    for analysis in analyses:
        if not analysis:
            continue
        total_points += analysis.total_test_points
        for frag in analysis.fragments:
            if frag.index not in seen_indices:
                seen_indices.add(frag.index)
                all_fragments.append(frag)
            else:
                existing = next(f for f in all_fragments if f.index == frag.index)
                existing.test_points.extend(frag.test_points)

    all_fragments.sort(key=lambda f: f.index)
    return AggregatedTestAnalysis(
        fragments=all_fragments,
        total_test_points=total_points,
        total_fragments=len(all_fragments),
        coverage_analysis=f"共 {len(all_fragments)} 个原文片段，{total_points} 个测试点",
    )


def _run_analysis_node(
    state: DocState,
    source_type: str,
    prompt_template: str,
    output_cls,
    collect_fn,
    format_fn,
    state_key: str,
) -> Dict:
    sections = _get_selected_sections(state)
    if not sections:
        return {state_key: None}

    items = collect_fn(sections)
    if not items:
        return {state_key: None}

    prompt = PromptTemplate.from_template(prompt_template)
    prompt_text = prompt.format(**{format_fn: _format_section_content(items)})

    try:
        result = _invoke_structured(_get_llm(0.3), prompt_text, output_cls)
        aggregated = _build_aggregated_analysis(result, source_type, f"{source_type}分析")
        return {state_key: aggregated}
    except Exception as e:
        print(f"{source_type}测试点分析失败: {e}")
        return {state_key: None}


def analysis_coordinator_node(state: DocState) -> Dict:
    result = {}
    for node_fn, state_key in [
        (table_analysis_node, "table_aggregated"),
        (func_desc_analysis_node, "func_desc_aggregated"),
        (business_rule_analysis_node, "business_rule_aggregated"),
        (exception_analysis_node, "exception_aggregated"),
        (process_analysis_node, "process_aggregated"),
    ]:
        ret = node_fn(state)
        if state_key in ret:
            result[state_key] = ret[state_key]
    return result


def table_analysis_node(state: DocState) -> Dict:
    sections = _get_selected_sections(state)
    if not sections:
        return {"table_aggregated": None}

    tables = _collect_table_data(sections)
    if not tables:
        return {"table_aggregated": None}

    prompt = PromptTemplate.from_template(TABLE_ANALYSIS_PROMPT)
    prompt_text = prompt.format(table_data=_format_table_data(tables))

    try:
        result = _invoke_structured(_get_llm(0.3), prompt_text, TableAnalysisResult)
        aggregated = _build_aggregated_analysis(result, "表格", "表格分析")
        return {"table_aggregated": aggregated}
    except Exception as e:
        print(f"表格测试点分析失败: {e}")
        return {"table_aggregated": None}


def func_desc_analysis_node(state: DocState) -> Dict:
    return _run_analysis_node(
        state, "功能描述", FUNC_DESC_ANALYSIS_PROMPT,
        FuncDescAnalysisResult,
        lambda s: _collect_function_sections(s, "func_desc"),
        "func_desc_content",
        "func_desc_aggregated",
    )


def business_rule_analysis_node(state: DocState) -> Dict:
    return _run_analysis_node(
        state, "业务规则", BUSINESS_RULE_ANALYSIS_PROMPT,
        BusinessRuleAnalysisResult,
        lambda s: _collect_function_sections(s, "business_rule"),
        "business_rule_content",
        "business_rule_aggregated",
    )


def exception_analysis_node(state: DocState) -> Dict:
    return _run_analysis_node(
        state, "异常处理", EXCEPTION_ANALYSIS_PROMPT,
        ExceptionAnalysisResult,
        lambda s: _collect_function_sections(s, "exception"),
        "exception_content",
        "exception_aggregated",
    )


def process_analysis_node(state: DocState) -> Dict:
    return _run_analysis_node(
        state, "处理流程", PROCESS_ANALYSIS_PROMPT,
        ProcessAnalysisResult,
        lambda s: _collect_function_sections(s, "process"),
        "process_content",
        "process_aggregated",
    )


def merge_aggregated_analysis_node(state: DocState) -> Dict:
    analyses = [
        state.get("table_aggregated"),
        state.get("func_desc_aggregated"),
        state.get("business_rule_aggregated"),
        state.get("exception_aggregated"),
        state.get("process_aggregated"),
    ]
    valid = [a for a in analyses if a is not None]
    if not valid:
        return {"aggregated_analysis": None}

    merged = _merge_aggregated_analyses(valid)
    return {"aggregated_analysis": merged}


def review_agent_node(state: DocState) -> Dict:
    aggregated = state.get("aggregated_analysis")
    if not aggregated or not aggregated.fragments:
        return {"approval_feedback": None, "is_approved": False}

    categories_text = ""
    for frag in aggregated.fragments:
        categories_text += f"\n【{frag.section_title}】共 {len(frag.test_points)} 个测试点"
        for tp in frag.test_points:
            categories_text += f"\n  - {tp.test_point_id}: {tp.description} (优先级: {tp.priority}, 类型: {tp.test_type})"

    prompt = PromptTemplate.from_template(REVIEW_AGENT_PROMPT)
    prompt_text = prompt.format(
        category_count=aggregated.total_fragments,
        total_test_points=aggregated.total_test_points,
        categories_text=categories_text,
    )

    try:
        result = _invoke_structured(_get_llm(0.2), prompt_text, ReviewResult)
        feedback = ApprovalFeedback(
            is_approved=result.is_approved,
            completeness_score=result.completeness_score,
            accuracy_score=result.accuracy_score,
            issues=result.issues,
            suggestions=result.suggestions,
            missing_test_points=result.missing_test_points,
        )
        return {"approval_feedback": feedback, "is_approved": feedback.is_approved}
    except Exception as e:
        print(f"审核Agent反思失败: {e}")
        return {"approval_feedback": None, "is_approved": False}


def user_review_node(state: DocState) -> Dict:
    aggregated = state.get("aggregated_analysis")
    if not aggregated:
        return {"user_review": None, "user_interrupted": False}

    user_input = interrupt(
        {
            "question": "请审核以下测试点分析结果",
            "total_fragments": aggregated.total_fragments,
            "total_test_points": aggregated.total_test_points,
            "instruction": "输入 'y' 或 'yes' 或 '批准' 表示通过；输入其他内容将作为修改意见重新分析",
        }
    )

    return process_user_review(state, user_input)


def process_user_review(state: DocState, user_input: str) -> Dict:
    user_input = user_input.strip().lower()
    if user_input in ("y", "yes", "批准", "通过"):
        return {
            "user_review": UserReviewStatus(reviewed=True, approved=True, review_comments="用户已批准", modifications=[]),
            "user_interrupted": False,
            "is_approved": True,
        }
    else:
        return {
            "user_review": UserReviewStatus(reviewed=True, approved=False, review_comments=user_input, modifications=[user_input]),
            "user_interrupted": False,
            "is_approved": False,
        }


def should_continue_after_user_review(state: DocState) -> str:
    user_review = state.get("user_review")
    if user_review and user_review.approved:
        return "approved"
    return "needs_revision"
