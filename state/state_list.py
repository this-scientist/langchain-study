from typing import TypedDict, List, Annotated, Optional
import operator
from langgraph.graph.message import add_messages
from struct_output.output_list import ParsedDoc

class AgentState(TypedDict):
    # 对话历史，持续累加
    messages: Annotated[List[str], operator.add]
    
    # 供用户选择的建议动作列表
    # 例如: ["执行代码", "修改文件", "运行测试", "退出"]
    suggested_actions: List[str]
    
    # 用户最终选择的动作
    chosen_action: Optional[str]
    
    # 当前任务是否结束
    is_finished: bool

class OverallState(TypedDict):
    raw_text: str
    struct_data: Optional[ParsedDoc]
    final_summary: str


