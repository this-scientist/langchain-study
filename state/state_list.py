from typing import TypedDict, List, Optional, Union
from struct_output.output_list import (
    StructuredDoc, ParsedDocWithMetadata, 
    TestPointAnalysis, ApprovalFeedback, TestAnalysisWithApproval,
    CategorizedTestAnalysis, CategorizedTestPoints, UserReviewStatus,
    AggregatedTestAnalysis,
)


class DocState(TypedDict):
    file_path: str  # 文档的完整文件路径
    raw_text_chunks: List[str]  # 文档原始文本分块列表
    parsed_data: Optional[Union[StructuredDoc, ParsedDocWithMetadata]]  # 解析后的结构化数据或带元数据的解析文档
    index_status: str  # 文档索引状态标识
    selected_section_indices: List[int]  # 用户选中的章节索引列表

    test_point_analysis: Optional[TestPointAnalysis]  # 测试点分析结果
    approval_feedback: Optional[ApprovalFeedback]  # 审批反馈信息
    test_analysis_result: Optional[TestAnalysisWithApproval]  # 带审批结论的测试分析结果
    iteration_count: int  # 当前迭代次数
    max_iterations: int  # 最大允许迭代次数
    is_approved: bool  # 是否已获批准

    categorized_analysis: Optional[CategorizedTestAnalysis]  # 分类后的测试分析结果
    table_test_points: Optional[CategorizedTestPoints]  # 表级测试点分类结果
    func_desc_test_points: Optional[CategorizedTestPoints]  # 功能描述测试点分类结果
    business_rule_test_points: Optional[CategorizedTestPoints]  # 业务规则测试点分类结果
    exception_test_points: Optional[CategorizedTestPoints]  # 异常测试点分类结果
    process_test_points: Optional[CategorizedTestPoints]  # 流程测试点分类结果

    user_review: Optional[UserReviewStatus]  # 用户评审状态
    user_interrupted: bool  # 用户是否中断流程
    resume_from_node: str  # 恢复流程时对应的节点标识

    aggregated_analysis: Optional[AggregatedTestAnalysis]  # 汇总后的测试分析结果
    table_aggregated: Optional[AggregatedTestAnalysis]  # 表级汇总测试分析结果
    func_desc_aggregated: Optional[AggregatedTestAnalysis]  # 功能描述汇总测试分析结果
    business_rule_aggregated: Optional[AggregatedTestAnalysis]  # 业务规则汇总测试分析结果
    exception_aggregated: Optional[AggregatedTestAnalysis]  # 异常汇总测试分析结果
    process_aggregated: Optional[AggregatedTestAnalysis]
    
    is_cancelled: bool  # 是否已手动取消/停止分析
