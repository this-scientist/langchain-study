from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver
from state.state_list import DocState
from node.test_analysis_nodes import (
    fetch_next_part_node,
    analysis_node,
    format_review_node,
)
from typing import Dict, List, Any, Optional


def should_continue(state: DocState) -> str:
    """决定是否继续处理下一个需求片段"""
    if state.get("is_cancelled"):
        return "end"
    
    if state.get("status") == "completed" or not state.get("current_part_id"):
        return "end"
        
    return "continue"

# --- 图的定义 ---
workflow = StateGraph(DocState)

# 添加节点
workflow.add_node("fetch_next_part", fetch_next_part_node)
workflow.add_node("analysis", analysis_node)
workflow.add_node("format_review", format_review_node)

# 设置入口点
workflow.set_entry_point("fetch_next_part")

# 编排流程
workflow.add_conditional_edges(
    "fetch_next_part",
    should_continue,
    {
        "continue": "analysis",
        "end": END
    }
)

workflow.add_edge("analysis", "format_review")
workflow.add_edge("format_review", "fetch_next_part")

# 编译工作流，添加持久化支持
checkpointer = MemorySaver()
app = workflow.compile(checkpointer=checkpointer)


def init_analysis_state(task_id: str, doc_id: str, file_path: str, part_ids: List[str]) -> DocState:
    """初始化分析状态"""
    return {
        "task_id": task_id,
        "doc_id": doc_id,
        "file_path": file_path,
        "pending_part_ids": part_ids,
        "current_part_id": None,
        "current_part_content": None,
        "current_part_type": None,
        "status": "starting",
        "progress": "准备开始分析...",
        "message": "",
        "format_issues": [],
        "last_saved_tp_ids": [],
        "is_cancelled": False,
    }

def run_task_analysis(task_id: str, doc_id: str, file_path: str, part_ids: List[str], thread_id: str = "default"):
    """执行分析任务"""
    initial_state = init_analysis_state(task_id, doc_id, file_path, part_ids)
    config = {"configurable": {"thread_id": thread_id}}
    
    # 异步执行或流式执行可以根据需要调整
    # 这里使用 invoke 执行完整流程
    result = app.invoke(initial_state, config=config)
    return result, config
