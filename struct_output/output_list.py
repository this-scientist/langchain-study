from pydantic import BaseModel, Field
from typing import List, Optional
# 意图进度跟踪模型，用于记录对话中用户意图的识别状态和槽位填充情况
class IntentProgress(BaseModel):
    main_intent: str = Field(description="主意图，如：维修、投诉、查询")
    extracted_slots: dict = Field(description="从用户话语中提取的参数，如：{'设备': '冰箱'}")
    missing_info: str = Field(description="为了完成任务，还需要问用户的一个最关键问题。如果不需要提问则为空。")
    is_complete: bool = Field(description="所有必要信息是否已集齐")

# 文档章节模型，表示文档中的一个章节及其层级和内容
class DocumentSection(BaseModel):
    title: str = Field(description="章节标题")
    level: int = Field(description="标题层级")
    content: str = Field(description="章节正文")

# 解析后的文档模型，包含多个章节和是否需要摘要的标志
class ParsedDoc(BaseModel):
    sections: List[DocumentSection]
    summary_needed: bool = Field(default=True)

# 章节模型，用于结构化文档中的单个章节
class Section(BaseModel):
    title: str = Field(description="章节标题")
    level: int = Field(description="标题层级")
    content: str = Field(description="该章节的正文内容")

# 结构化文档模型，包含多个章节
class StructuredDoc(BaseModel):
    sections: List[Section]

# 表格数据模型，用于表示文档中的表格结构和内容
class TableData(BaseModel):
    headers: List[str] = Field(description="表格列标题")
    rows: List[List[str]] = Field(description="表格数据行")
    caption: Optional[str] = Field(default=None, description="表格标题/说明")

# 文档章节元数据模型，记录章节的多级标题层级信息
class DocSectionMetadata(BaseModel):
    level_1: str = Field(description="一级标题")
    level_2: str = Field(description="二级标题")
    level_3: str = Field(description="三级标题")
    level_4: Optional[str] = Field(default=None, description="四级标题")

# 功能章节模型，描述文档中某个功能相关的部分内容
class FunctionSection(BaseModel):
    section_type: str = Field(description="部分类型：功能描述、业务规则、操作权限、处理过程、异常处理等")
    content: str = Field(description="该部分的详细内容")
    tables: List[TableData] = Field(default_factory=list, description="该部分包含的表格")

# 带元数据的文档章节模型，包含完整的章节信息和功能分解
class DocSectionWithMetadata(BaseModel):
    title: str = Field(description="完整标题")
    level: int = Field(description="标题层级，固定为3")
    content: str = Field(description="章节正文内容")
    metadata: DocSectionMetadata = Field(description="层级元数据")
    function_sections: List[FunctionSection] = Field(default_factory=list, description="功能分解部分")
    tables: List[TableData] = Field(default_factory=list, description="章节内的所有表格")

# 带元数据的解析文档模型，包含多个带元数据的章节和统计信息
class ParsedDocWithMetadata(BaseModel):
    sections: List[DocSectionWithMetadata] = Field(description="解析后的章节列表")
    total_count: int = Field(description="总章节数")

# 测试点模型，描述从文档中提取的单个测试点信息
class TestPoint(BaseModel):
    test_point_id: str = Field(description="测试点唯一标识")
    description: str = Field(description="测试点描述")
    source_section: str = Field(description="原文来源章节")
    source_type: str = Field(description="来源类型：功能描述、业务规则、操作权限、处理过程、异常处理、表格")
    source_content: str = Field(description="原文内容片段")
    related_sections: List[str] = Field(default_factory=list, description="关联的其他章节/部分")
    priority: str = Field(description="优先级：高、中、低")
    test_type: str = Field(description="测试类型：功能测试、边界测试、异常测试、权限测试等")
    steps: List[str] = Field(default_factory=list, description="测试步骤，如 ['1. 登录系统', '2. 进入功能页面', '3. 执行测试操作', '4. 观察结果']")
    expected_results: List[str] = Field(default_factory=list, description="预期结果，与 steps 序号一一对应")

# 测试点分析模型，包含某个功能的全部测试点列表和分析结果
class TestPointAnalysis(BaseModel):
    function_title: str = Field(description="功能名称")
    test_points: List[TestPoint] = Field(description="测试点列表")
    coverage_analysis: str = Field(description="测试覆盖率分析")
    missing_areas: List[str] = Field(default_factory=list, description="可能遗漏的测试区域")

# 审批反馈模型，记录测试点分析的审批结果和评分
class ApprovalFeedback(BaseModel):
    is_approved: bool = Field(description="是否通过审批")
    completeness_score: float = Field(description="完整性评分 0-1")
    accuracy_score: float = Field(description="准确性评分 0-1")
    issues: List[str] = Field(default_factory=list, description="发现的问题")
    suggestions: List[str] = Field(default_factory=list, description="改进建议")
    missing_test_points: List[str] = Field(default_factory=list, description="遗漏的测试点")

# 分类测试点集合，按来源类型分组
class CategorizedTestPoints(BaseModel):
    source_type: str = Field(description="来源类型：表格、功能描述、业务规则、异常处理、处理流程")
    test_points: List[TestPoint] = Field(default_factory=list, description="该分类下的测试点列表")
    analysis_summary: str = Field(default="", description="该分类的分析摘要")

# 分类测试点分析结果，包含所有分类的测试点
class CategorizedTestAnalysis(BaseModel):
    function_title: str = Field(description="功能名称")
    categories: List[CategorizedTestPoints] = Field(default_factory=list, description="各分类的测试点集合")
    all_test_points: List[TestPoint] = Field(default_factory=list, description="所有测试点汇总")
    coverage_analysis: str = Field(default="", description="整体覆盖率分析")
    missing_areas: List[str] = Field(default_factory=list, description="可能遗漏的测试区域")

# 用户审核状态
class UserReviewStatus(BaseModel):
    reviewed: bool = Field(default=False, description="用户是否已审核")
    approved: bool = Field(default=False, description="用户是否批准")
    review_comments: str = Field(default="", description="用户审核意见")
    modifications: List[str] = Field(default_factory=list, description="用户要求的修改")

# 带审批的测试分析模型，整合测试点分析和审批反馈的完整结果
class TestAnalysisWithApproval(BaseModel):
    analysis: TestPointAnalysis = Field(description="测试点分析结果")
    approval: ApprovalFeedback = Field(description="审批反馈")
    iteration_count: int = Field(description="迭代次数")
    is_final: bool = Field(description="是否最终版本")


# ========== 新结构：按原文片段聚合测试点 ==========

class SourceFragmentRef(BaseModel):
    fragment_index: int = Field(description="原文片段索引")
    source_section: str = Field(description="原文来源章节标题")


class AggregatedTestPoint(BaseModel):
    test_point_id: str = Field(description="测试点唯一标识")
    description: str = Field(description="测试点描述")
    source_fragment_index: int = Field(description="关联的原文片段索引")
    priority: str = Field(description="优先级：高、中、低")
    test_type: str = Field(description="测试类型")
    source_type: str = Field(description="来源分析类型：表格/功能描述/业务规则/异常处理/处理流程")
    steps: List[str] = Field(default_factory=list, description="测试步骤")
    expected_results: List[str] = Field(default_factory=list, description="预期结果，与 steps 序号一一对应")


class SourceFragmentWithPoints(BaseModel):
    index: int = Field(description="片段索引")
    section_title: str = Field(description="来源章节标题")
    content: str = Field(description="原文内容")
    test_points: List[AggregatedTestPoint] = Field(default_factory=list, description="该片段关联的所有测试点")


class AggregatedTestAnalysis(BaseModel):
    fragments: List[SourceFragmentWithPoints] = Field(default_factory=list, description="按原文片段聚合的测试点列表")
    total_test_points: int = Field(default=0, description="测试点总数")
    total_fragments: int = Field(default=0, description="原文片段总数")
    coverage_analysis: str = Field(default="", description="整体覆盖率分析")