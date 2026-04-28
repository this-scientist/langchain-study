from typing import TypedDict, List, Optional, Union, Dict, Any

class DocState(TypedDict):
    # 基础信息
    task_id: str                   # 数据库中的 analysis_tasks.id
    doc_id: str                    # 数据库中的 documents.id
    file_path: str                 # 文档路径
    
    # 当前处理的需求片段信息
    current_part_id: Optional[str]  # 当前正在处理的 section_function_parts.id
    current_part_content: Optional[str] # 当前处理的文本内容
    current_part_type: Optional[str]    # 当前处理的类型 (table, func_desc, etc.)
    
    # 选中的待处理需求列表 (function_part_id 列表)
    pending_part_ids: List[str]
    
    # 运行状态
    status: str                    # starting, analyzing, completed, error
    progress: str                  # 进度描述
    message: str                   # 错误或提示信息
    
    # 格式审查结果汇总 (临时存储在 state 中，随后入库)
    format_issues: List[Dict[str, Any]]
    
    # 临时存储分析节点生成的 ID，供审查节点使用
    last_saved_tp_ids: Optional[List[str]]
    
    is_cancelled: bool             # 是否已停止分析
