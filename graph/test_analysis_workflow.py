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
)
from struct_output.output_list import (
    TestAnalysisWithApproval,
    AggregatedTestAnalysis,
)
from typing import Dict


def create_final_result(state: DocState) -> Dict:
    aggregated = state.get("aggregated_analysis")
    approval = state.get("approval_feedback")
    user_review = state.get("user_review")

    if aggregated and approval:
        from struct_output.output_list import TestPointAnalysis, TestPoint
        test_points = []
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
        merged_analysis = TestPointAnalysis(
            function_title="文档功能测试点分析",
            test_points=test_points,
            coverage_analysis=aggregated.coverage_analysis,
            missing_areas=[],
        )
        final_result = TestAnalysisWithApproval(
            analysis=merged_analysis,
            approval=approval,
            iteration_count=1,
            is_final=(user_review and user_review.approved) if user_review else False
        )
        return {"test_analysis_result": final_result}

    return {"test_analysis_result": None}


def route_after_parser(state: DocState) -> str:
    return "indexer"


workflow = StateGraph(DocState)

workflow.add_node("parser", word_parser_node)
workflow.add_node("indexer", word_indexer_node)

workflow.add_node("analysis_coordinator", analysis_coordinator_node)
workflow.add_node("merge_aggregated", merge_aggregated_analysis_node)
workflow.add_node("review_agent", review_agent_node)
workflow.add_node("user_review", user_review_node)
workflow.add_node("finalizer", create_final_result)

workflow.set_entry_point("parser")

workflow.add_edge("parser", "indexer")
workflow.add_edge("indexer", "analysis_coordinator")
workflow.add_edge("analysis_coordinator", "merge_aggregated")
workflow.add_edge("merge_aggregated", "review_agent")
workflow.add_edge("review_agent", "user_review")

workflow.add_conditional_edges(
    "user_review",
    should_continue_after_user_review,
    {
        "approved": "finalizer",
        "needs_revision": "analysis_coordinator"
    }
)

workflow.add_edge("finalizer", END)

checkpointer = MemorySaver()

app = workflow.compile(checkpointer=checkpointer)


def run_test_point_analysis(doc_path: str, max_iterations: int = 3, selected_indices: List[int] = None):
    initial_state: DocState = {
        "file_path": doc_path,
        "raw_text_chunks": [],
        "parsed_data": None,
        "index_status": "Pending",
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
    }

    config = {"configurable": {"thread_id": "test_analysis_1"}}

    result = app.invoke(initial_state, config=config)
    return result, config


def run_with_user_interrupt(doc_path: str, max_iterations: int = 3, thread_id: str = "default", selected_indices: List[int] = None):
    initial_state: DocState = {
        "file_path": doc_path,
        "raw_text_chunks": [],
        "parsed_data": None,
        "index_status": "Pending",
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
    }

    config = {"configurable": {"thread_id": thread_id}}

    try:
        result = app.invoke(initial_state, config=config)
    except Exception:
        print(f"\n流程在用户审核节点暂停。")
        result = None

    return result, config


def resume_after_user_review(config: dict, user_input: str):
    from langgraph.types import Command

    try:
        result = app.invoke(Command(resume=user_input), config=config)
        return result
    except Exception as e:
        print(f"恢复流程失败: {e}")
        return None


if __name__ == "__main__":
    print("=" * 80)
