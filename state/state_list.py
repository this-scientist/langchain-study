from typing import TypedDict, List, Optional, Union
from struct_output.output_list import (
    StructuredDoc, ParsedDocWithMetadata, 
    TestPointAnalysis, ApprovalFeedback, TestAnalysisWithApproval,
    CategorizedTestAnalysis, CategorizedTestPoints, UserReviewStatus,
    AggregatedTestAnalysis,
)


class DocState(TypedDict):
    file_path: str
    raw_text_chunks: List[str]
    parsed_data: Optional[Union[StructuredDoc, ParsedDocWithMetadata]]
    index_status: str
    selected_section_indices: List[int]

    test_point_analysis: Optional[TestPointAnalysis]
    approval_feedback: Optional[ApprovalFeedback]
    test_analysis_result: Optional[TestAnalysisWithApproval]
    iteration_count: int
    max_iterations: int
    is_approved: bool

    categorized_analysis: Optional[CategorizedTestAnalysis]
    table_test_points: Optional[CategorizedTestPoints]
    func_desc_test_points: Optional[CategorizedTestPoints]
    business_rule_test_points: Optional[CategorizedTestPoints]
    exception_test_points: Optional[CategorizedTestPoints]
    process_test_points: Optional[CategorizedTestPoints]

    user_review: Optional[UserReviewStatus]
    user_interrupted: bool
    resume_from_node: str

    aggregated_analysis: Optional[AggregatedTestAnalysis]
    table_aggregated: Optional[AggregatedTestAnalysis]
    func_desc_aggregated: Optional[AggregatedTestAnalysis]
    business_rule_aggregated: Optional[AggregatedTestAnalysis]
    exception_aggregated: Optional[AggregatedTestAnalysis]
    process_aggregated: Optional[AggregatedTestAnalysis]
