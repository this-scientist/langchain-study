from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver
from state.state_list import DocState
from node.node_list import word_parser_node, word_indexer_node
from node.test_analysis_nodes import (
    analysis_coordinator_node,
    review_agent_node,
    user_review_node,
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
        # 支持字典格式和 Pydantic 模型格式
        fragments = aggregated.get("fragments") if isinstance(aggregated, dict) else getattr(aggregated, "fragments", [])
        coverage_analysis = aggregated.get("coverage_analysis") if isinstance(aggregated, dict) else getattr(aggregated, "coverage_analysis", "")
        for frag in fragments:
            frag_test_points = frag.get("test_points") if isinstance(frag, dict) else getattr(frag, "test_points", [])
            frag_section_title = frag.get("section_title") if isinstance(frag, dict) else getattr(frag, "section_title", "")
            frag_content = frag.get("content") if isinstance(frag, dict) else getattr(frag, "content", "")
            for tp in frag_test_points:
                tp_id = tp.get("test_point_id") if isinstance(tp, dict) else getattr(tp, "test_point_id", "")
                tp_desc = tp.get("description") if isinstance(tp, dict) else getattr(tp, "description", "")
                tp_source_type = tp.get("source_type") if isinstance(tp, dict) else getattr(tp, "source_type", "")
                tp_priority = tp.get("priority") if isinstance(tp, dict) else getattr(tp, "priority", "")
                tp_type = tp.get("test_type") if isinstance(tp, dict) else getattr(tp, "test_type", "")
                tp_steps = tp.get("steps") if isinstance(tp, dict) else getattr(tp, "steps", [])
                tp_expected = tp.get("expected_results") if isinstance(tp, dict) else getattr(tp, "expected_results", [])
                test_points.append(TestPoint(
                    test_point_id=tp_id,
                    description=tp_desc,
                    source_section=frag_section_title,
                    source_type=tp_source_type,
                    source_content=frag_content,
                    priority=tp_priority,
                    test_type=tp_type,
                    steps=tp_steps,
                    expected_results=tp_expected,
                ))
        
        # 构造汇总分析对象
        merged_analysis = TestPointAnalysis(
            function_title="文档功能测试点分析",
            test_points=test_points,
            coverage_analysis=coverage_analysis,
            missing_areas=[],
        )
        
        from struct_output.output_list import ApprovalFeedback
        approval_obj = ApprovalFeedback.model_validate(approval) if isinstance(approval, dict) else approval
        is_approved = getattr(user_review, "approved", False) if user_review else False

        final_result = TestAnalysisWithApproval(
            analysis=merged_analysis,
            approval=approval_obj,
            iteration_count=iteration_count,
            is_final=is_approved,
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
workflow.add_node("review_agent", review_agent_node)
workflow.add_node("user_review", user_review_node)
workflow.add_node("finalizer", create_final_result)

# 设置入口点：因为解析已在外部完成，直接进入分析迭代
workflow.set_entry_point("increment_iteration")

# 编排线性流程
workflow.add_edge("increment_iteration", "analysis_coordinator")
workflow.add_edge("analysis_coordinator", "review_agent")
workflow.add_edge("review_agent", "user_review")

# 处理用户审核后的条件跳转
def should_continue(state: DocState) -> str:
    if state.get("is_cancelled"):
        return "max_reached"

    if not state.get("aggregated_analysis"):
        print("无分析数据，流程终止。")
        return "max_reached"

    user_review = state.get("user_review")
    if user_review and getattr(user_review, "approved", False):
        return "approved"
    
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
        "approved": "finalizer",
        "needs_revision": "increment_iteration",
        "max_reached": "finalizer"
    }
)

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
