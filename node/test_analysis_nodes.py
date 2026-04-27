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
    AnalysisResult, ReviewResult,
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
    """
    初始化并返回一个 ChatOpenAI 实例。
    
    Args:
        temperature: 生成随机性，默认为 0.3。
        
    Returns:
        ChatOpenAI: 配置好的语言模型实例。
    """
    return ChatOpenAI(
        model=GLM_MODEL,
        temperature=temperature,
        api_key=GLM_API_KEY,
        base_url=GLM_BASE_URL,
    )


def _invoke_structured(llm: ChatOpenAI, prompt_text: str, output_cls) -> BaseModel:
    """
    调用大语言模型并尝试将结果解析为结构化的 Pydantic 模型。
    
    Args:
        llm: 语言模型实例。
        prompt_text: 提示词文本。
        output_cls: 期望输出的 Pydantic 类。
        
    Returns:
        BaseModel: 解析后的结构化数据。
    """
    raw = llm.invoke(prompt_text)
    content = raw.content.strip()
    content = re.sub(r'^```(?:markdown|json|)\s*', '', content)
    content = re.sub(r'\s*```$', '', content)
    content = content.strip()
    data = json.loads(content)
    return output_cls.model_validate(data)


def _get_selected_sections(state: DocState) -> List[DocSectionWithMetadata]:
    """
    从状态中获取选中的文档章节。
    
    Args:
        state: 当前图的状态。
        
    Returns:
        List[DocSectionWithMetadata]: 选中的章节列表。
    """
    sections = state.get("parsed_data")
    if not sections or not sections.sections:
        return []
    indices = state.get("selected_section_indices", [])
    if not indices:
        return sections.sections
    return [sections.sections[i] for i in indices if i < len(sections.sections)]


def _collect_table_data(sections: List[DocSectionWithMetadata]) -> List[Tuple[str, TableData]]:
    """
    从给定的章节列表中收集所有表格数据。
    
    Args:
        sections: 章节列表。
        
    Returns:
        List[Tuple[str, TableData]]: 包含章节标题和表格数据的元组列表。
    """
    tables = []
    for sec in sections:
        for t in sec.tables:
            tables.append((sec.title, t))
        for fs in sec.function_sections:
            for t in fs.tables:
                tables.append((f"{sec.title} - {fs.section_type}", t))
    return tables


def _collect_function_sections(sections: List[DocSectionWithMetadata], section_type: str) -> List[Tuple[str, str, str]]:
    """
    从给定的章节列表中收集特定类型的子章节内容。
    
    Args:
        sections: 章节列表。
        section_type: 目标子章节类型。
        
    Returns:
        List[Tuple[str, str, str]]: 包含主章节标题、子章节类型和内容的元组列表。
    """
    results = []
    for sec in sections:
        for fs in sec.function_sections:
            mapped = SECTION_TYPE_MAP.get(fs.section_type, "")
            if mapped == section_type:
                results.append((sec.title, fs.section_type, fs.content))
    return results


def _format_table_data(tables: List[Tuple[str, TableData]]) -> str:
    """
    将表格数据格式化为字符串，用于提示词输入。
    
    Args:
        tables: 包含章节标题和表格数据的元组列表。
        
    Returns:
        str: 格式化后的表格字符串。
    """
    lines = []
    for i, (section_title, table) in enumerate(tables, 1):
        lines.append(f"\n【表格{i}】来源章节: {section_title}")
        lines.append(f"列标题: {', '.join(table.headers)}")
        for j, row in enumerate(table.rows, 1):
            lines.append(f"  行{j}: {', '.join(row)}")
    return "\n".join(lines)


def _format_section_content(items: List[Tuple[str, str, str]], max_len: int = 500) -> str:
    """
    将章节内容格式化为字符串，用于提示词输入。
    
    Args:
        items: 包含标题、类型和内容的元组列表。
        max_len: 每个章节内容的最大长度。
        
    Returns:
        str: 格式化后的内容字符串。
    """
    lines = []
    for section_title, stype, content in items:
        lines.append(f"\n【{section_title} - {stype}】\n{content[:max_len]}")
    return "\n".join(lines)




def _build_aggregated_analysis(
    result,
    source_type: str,
    section_title: str,
) -> AggregatedTestAnalysis:
    """
    将原始分析结果构建为聚合的测试点分析对象。
    
    Args:
        result: 原始分析结果对象（包含测试点和来源片段）。
        source_type: 来源类型（如“表格”、“功能描述”等）。
        section_title: 章节标题。
        
    Returns:
        AggregatedTestAnalysis: 聚合后的分析结果。
    """
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
    """
    将多个聚合分析结果合并为一个。
    
    Args:
        analyses: 聚合分析结果列表。
        
    Returns:
        AggregatedTestAnalysis: 合并后的聚合分析结果。
    """
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
    """
    通用的分析节点执行逻辑。
    
    Args:
        state: 当前图的状态。
        source_type: 来源类型。
        prompt_template: 提示词模板。
        output_cls: 输出的结构化类。
        collect_fn: 数据收集函数。
        format_fn: 格式化参数名。
        state_key: 状态中存储结果的键。
        
    Returns:
        Dict: 更新后的状态片段。
    """
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
    """
    分析协调器节点，按顺序执行各个具体的分析节点。
    
    Args:
        state: 当前图的状态。
        
    Returns:
        Dict: 包含所有分析结果的聚合字典。
    """
    if state.get("is_cancelled"):
        print("分析已取消，停止执行。")
        return {}

    # 获取当前已有的聚合结果（如果有的话）
    result = {
        "table_aggregated": state.get("table_aggregated"),
        "func_desc_aggregated": state.get("func_desc_aggregated"),
        "business_rule_aggregated": state.get("business_rule_aggregated"),
        "exception_aggregated": state.get("exception_aggregated"),
        "process_aggregated": state.get("process_aggregated"),
    }
    
    # 依次运行每个子节点并更新 result
    for node_fn, state_key in [
        (table_analysis_node, "table_aggregated"),
        (func_desc_analysis_node, "func_desc_aggregated"),
        (business_rule_analysis_node, "business_rule_aggregated"),
        (exception_analysis_node, "exception_aggregated"),
        (process_analysis_node, "process_aggregated"),
    ]:
        ret = node_fn(state)
        if ret.get(state_key) is not None:
            result[state_key] = ret[state_key]
            
    return result


def table_analysis_node(state: DocState) -> Dict:
    """
    表格分析节点，专门处理文档中的表格测试点。
    
    Args:
        state: 当前图的状态。
        
    Returns:
        Dict: 包含表格聚合分析结果的字典。
    """
    sections = _get_selected_sections(state)
    if not sections:
        return {"table_aggregated": None}

    tables = _collect_table_data(sections)
    if not tables:
        return {"table_aggregated": None}

    prompt = PromptTemplate.from_template(TABLE_ANALYSIS_PROMPT)
    prompt_text = prompt.format(table_data=_format_table_data(tables))

    try:
        result = _invoke_structured(_get_llm(0.3), prompt_text, AnalysisResult)
        aggregated = _build_aggregated_analysis(result, "表格", "表格分析")
        return {"table_aggregated": aggregated}
    except Exception as e:
        print(f"表格测试点分析失败: {e}")
        return {"table_aggregated": None}


def func_desc_analysis_node(state: DocState) -> Dict:
    """
    功能描述分析节点。
    
    Args:
        state: 当前图的状态。
        
    Returns:
        Dict: 包含功能描述聚合分析结果的字典。
    """
    return _run_analysis_node(
        state, "功能描述", FUNC_DESC_ANALYSIS_PROMPT,
        AnalysisResult,
        lambda s: _collect_function_sections(s, "func_desc"),
        "func_desc_content",
        "func_desc_aggregated",
    )


def business_rule_analysis_node(state: DocState) -> Dict:
    """
    业务规则分析节点。
    
    Args:
        state: 当前图的状态。
        
    Returns:
        Dict: 包含业务规则聚合分析结果的字典。
    """
    return _run_analysis_node(
        state, "业务规则", BUSINESS_RULE_ANALYSIS_PROMPT,
        AnalysisResult,
        lambda s: _collect_function_sections(s, "business_rule"),
        "business_rule_content",
        "business_rule_aggregated",
    )


def exception_analysis_node(state: DocState) -> Dict:
    """
    异常处理分析节点。
    
    Args:
        state: 当前图的状态。
        
    Returns:
        Dict: 包含异常处理聚合分析结果的字典。
    """
    return _run_analysis_node(
        state, "异常处理", EXCEPTION_ANALYSIS_PROMPT,
        AnalysisResult,
        lambda s: _collect_function_sections(s, "exception"),
        "exception_content",
        "exception_aggregated",
    )


def process_analysis_node(state: DocState) -> Dict:
    """
    处理流程分析节点。
    
    Args:
        state: 当前图的状态。
        
    Returns:
        Dict: 包含处理流程聚合分析结果的字典。
    """
    return _run_analysis_node(
        state, "处理流程", PROCESS_ANALYSIS_PROMPT,
        AnalysisResult,
        lambda s: _collect_function_sections(s, "process"),
        "process_content",
        "process_aggregated",
    )


def merge_aggregated_analysis_node(state: DocState) -> Dict:
    """
    聚合所有分析节点的输出。
    
    Args:
        state: 当前图的状态。
        
    Returns:
        Dict: 包含最终聚合分析结果的字典。
    """
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
    """
    审核 Agent 节点，利用 AI 对聚合后的测试点进行反思和评分。
    
    Args:
        state: 当前图的状态。
        
    Returns:
        Dict: 包含审核反馈和是否批准的状态。
    """
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
    """
    用户审核节点，暂停执行并等待人工确认。
    
    Args:
        state: 当前图的状态。
        
    Returns:
        Dict: 包含用户审核结果的字典。
    """
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
    """
    处理用户输入的审核意见。
    
    Args:
        state: 当前图的状态。
        user_input: 用户的输入文本。
        
    Returns:
        Dict: 包含用户审核状态的字典。
    """
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
    """
    用户审核后的决策边，决定是进入下一步还是重新分析。
    
    Args:
        state: 当前图的状态。
        
    Returns:
        str: 下一步的路由标识。
    """
    user_review = state.get("user_review")
    if user_review and user_review.approved:
        return "approved"
    return "needs_revision"


def test_case_generation_node(state: DocState) -> Dict:
    """
    用例文档生成节点。
    目前为占位实现，后续将根据审核通过的测试点生成完整的测试用例文档。
    
    Args:
        state: 当前图的状态。
        
    Returns:
        Dict: 包含生成结果的状态片段。
    """
    # TODO: 实现具体的用例文档生成逻辑
    print("正在生成用例文档...")
    return {"message": "用例文档生成成功（占位）"}
