from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver
from state.state_list import DocState
from node.node_list import word_parser_node, word_indexer_node
from node.test_analysis_nodes import (
    analysis_coordinator_node,
    merge_aggregated_analysis_node,
    review_agent_node,
    user_review_node,
    should_continue_after_user_review,
    test_case_generation_node,
)
from struct_output.output_list import (
    TestAnalysisWithApproval,
    AggregatedTestAnalysis,
)
from typing import Dict, List, Any


def _get_initial_state(doc_path: str, max_iterations: int, selected_indices: List[int] = None, parsed_data: Any = None) -> DocState:
    """
    构造图的初始状态对象。
    
    Args:
        doc_path: 文档路径。
        max_iterations: 最大迭代次数。
        selected_indices: 选中的章节索引列表。
        parsed_data: 预先解析好的文档数据（可选）。
        
    Returns:
        DocState: 初始化后的状态字典。
    """
    return {
        "file_path": doc_path,
        "raw_text_chunks": [],
        "parsed_data": parsed_data,
        "index_status": "Indexed" if parsed_data else "Pending",
        "selected_section_indices": selected_indices or [],
        "test_point_analysis": None,
        "approval_feedback": None,
        "test_analysis_result": None,
        "iteration_count": 0,
        "max_iterations": max_iterations,
        "is_approved": False,
        "categorized_analysis": None,
        "table_test_points": None,
        "func_desc_test_points": None,
        "business_rule_test_points": None,
        "exception_test_points": None,
        "process_test_points": None,
        "user_review": None,
        "user_interrupted": False,
        "resume_from_node": "",
        "aggregated_analysis": None,
        "table_aggregated": None,
        "func_desc_aggregated": None,
        "business_rule_aggregated": None,
        "exception_aggregated": None,
        "process_aggregated": None,
        "is_cancelled": False,
    }


def create_final_result(state: DocState) -> Dict:
    """
    在流程结束前，将聚合的分析结果和审核反馈转换为最终的输出格式。
    
    Args:
        state: 当前图的状态。
        
    Returns:
        Dict: 包含最终 test_analysis_result 的字典。
    """
    aggregated = state.get("aggregated_analysis")
    approval = state.get("approval_feedback")
    user_review = state.get("user_review")
    iteration_count = state.get("iteration_count", 0)

    if aggregated and approval:
        from struct_output.output_list import TestPointAnalysis, TestPoint
        test_points = []
        # 将聚合的片段及其测试点展平为扁平列表
        for frag in aggregated.fragments:
            for tp in frag.test_points:
                test_points.append(TestPoint(
                    test_point_id=tp.test_point_id,
                    description=tp.description,
                    source_section=frag.section_title,
                    source_type=tp.source_type,
                    source_content=frag.content,
                    priority=tp.priority,
                    test_type=tp.test_type,
                    steps=tp.steps,
                    expected_results=tp.expected_results,
                ))
        
        # 构造汇总分析对象
        merged_analysis = TestPointAnalysis(
            function_title="文档功能测试点分析",
            test_points=test_points,
            coverage_analysis=aggregated.coverage_analysis,
            missing_areas=[],
        )
        
        # 构造最终带审核信息的输出
        final_result = TestAnalysisWithApproval(
            analysis=merged_analysis,
            approval=approval,
            iteration_count=iteration_count,
            is_final=(user_review and user_review.approved) if user_review else False
        )
        return {"test_analysis_result": final_result}

    return {"test_analysis_result": None}


def increment_iteration_node(state: DocState) -> Dict:
    """
    增加迭代计数器。
    
    Args:
        state: 当前图的状态。
        
    Returns:
        Dict: 更新后的 iteration_count。
    """
    current_count = state.get("iteration_count", 0)
    return {"iteration_count": current_count + 1}


# --- 图的定义 ---
workflow = StateGraph(DocState)

# 添加测试分析相关节点
workflow.add_node("increment_iteration", increment_iteration_node)
workflow.add_node("analysis_coordinator", analysis_coordinator_node)
workflow.add_node("merge_aggregated", merge_aggregated_analysis_node)
workflow.add_node("review_agent", review_agent_node)
workflow.add_node("user_review", user_review_node)
workflow.add_node("test_case_generation", test_case_generation_node)
workflow.add_node("finalizer", create_final_result)

# 设置入口点：因为解析已在外部完成，直接进入分析迭代
workflow.set_entry_point("increment_iteration")

# 编排线性流程
workflow.add_edge("increment_iteration", "analysis_coordinator")
workflow.add_edge("analysis_coordinator", "merge_aggregated")
workflow.add_edge("merge_aggregated", "review_agent")
workflow.add_edge("review_agent", "user_review")

# 处理用户审核后的条件跳转
def should_continue(state: DocState) -> str:
    """
    根据用户审核结果和迭代次数决定流程走向。
    """
    if state.get("is_cancelled"):
        return "max_reached"

    user_review = state.get("user_review")
    if user_review and user_review.approved:
        return "approved"
    
    # 检查是否超过最大迭代次数
    current_count = state.get("iteration_count", 0)
    max_count = state.get("max_iterations", 3)
    if current_count >= max_count:
        print(f"达到最大迭代次数 ({max_count})，流程终止。")
        return "max_reached"
        
    return "needs_revision"

workflow.add_conditional_edges(
    "user_review",
    should_continue,
    {
        "approved": "test_case_generation",
        "needs_revision": "increment_iteration",
        "max_reached": "finalizer"
    }
)

workflow.add_edge("test_case_generation", "finalizer")
workflow.add_edge("finalizer", END)

# 编译工作流，添加持久化支持
checkpointer = MemorySaver()
app = workflow.compile(checkpointer=checkpointer)


def run_test_point_analysis(doc_path: str, max_iterations: int = 3, selected_indices: List[int] = None, parsed_data: Any = None):
    """
    运行测试点分析流程（自动执行，不推荐用于生产，因为缺少人工干预）。
    """
    initial_state = _get_initial_state(doc_path, max_iterations, selected_indices, parsed_data)
    config = {"configurable": {"thread_id": "test_analysis_1"}}
    result = app.invoke(initial_state, config=config)
    return result, config


def run_with_user_interrupt(doc_path: str, max_iterations: int = 3, thread_id: str = "default", selected_indices: List[int] = None, parsed_data: Any = None):
    """
    运行测试点分析流程，支持在用户审核节点中断。
    """
    initial_state = _get_initial_state(doc_path, max_iterations, selected_indices, parsed_data)
    config = {"configurable": {"thread_id": thread_id}}

    try:
        # app.invoke 在遇到 interrupt 时会抛出异常或停止执行
        result = app.invoke(initial_state, config=config)
    except Exception:
        print(f"\n流程在用户审核节点暂停。")
        result = None

    return result, config


def resume_after_user_review(config: dict, user_input: str):
    """
    在用户提供反馈后恢复流程执行。
    
    Args:
        config: 包含 thread_id 的配置字典。
        user_input: 用户的审核意见（'y'/'n' 或具体修改建议）。
        
    Returns:
        Any: 流程恢复后的执行结果。
    """
    from langgraph.types import Command

    try:
        result = app.invoke(Command(resume=user_input), config=config)
        return result
    except Exception as e:
        print(f"恢复流程失败: {e}")
        return None


if __name__ == "__main__":
    print("=" * 80)
