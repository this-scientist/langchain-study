from pydantic import BaseModel, Field
from typing import List, Optional


class SourceFragmentRef(BaseModel):
    fragment_index: int = Field(description="原文片段索引，对应 source_fragments 列表中的位置")
    source_section: str = Field(description="原文来源章节标题")


class TestPointItem(BaseModel):
    test_point_id: str = Field(description="测试点唯一标识")
    description: str = Field(description="测试点描述（原子性，一个测试点只验证一个独立场景）")
    source_fragment_index: int = Field(description="关联的原文片段索引")
    priority: str = Field(description="优先级：高、中、低")
    test_type: str = Field(description="测试类型")
    steps: List[str] = Field(default_factory=list, description="测试步骤，格式如 ['1. 登录系统', '2. 进入功能页面', '3. 执行测试操作', '4. 观察结果']")
    expected_results: List[str] = Field(default_factory=list, description="预期结果，与 steps 序号一一对应，如 ['1. 页面正常打开', '2. 数据正确加载', '3. 操作成功', '4.结果符合预期']")


class SourceFragment(BaseModel):
    index: int = Field(description="片段索引")
    section_title: str = Field(description="来源章节标题")
    content: str = Field(description="原文内容片段")


class TableAnalysisResult(BaseModel):
    source_fragments: List[SourceFragment] = Field(description="所有引用的原文片段（去重）")
    test_points: List[TestPointItem] = Field(description="测试点列表，通过 source_fragment_index 关联原文")
    coverage_analysis: str = Field(description="测试覆盖率分析")


class FuncDescAnalysisResult(BaseModel):
    source_fragments: List[SourceFragment] = Field(description="所有引用的原文片段（去重）")
    test_points: List[TestPointItem] = Field(description="测试点列表，通过 source_fragment_index 关联原文")
    coverage_analysis: str = Field(description="测试覆盖率分析")


class BusinessRuleAnalysisResult(BaseModel):
    source_fragments: List[SourceFragment] = Field(description="所有引用的原文片段（去重）")
    test_points: List[TestPointItem] = Field(description="测试点列表，通过 source_fragment_index 关联原文")
    coverage_analysis: str = Field(description="测试覆盖率分析")


class ExceptionAnalysisResult(BaseModel):
    source_fragments: List[SourceFragment] = Field(description="所有引用的原文片段（去重）")
    test_points: List[TestPointItem] = Field(description="测试点列表，通过 source_fragment_index 关联原文")
    coverage_analysis: str = Field(description="测试覆盖率分析")


class ProcessAnalysisResult(BaseModel):
    source_fragments: List[SourceFragment] = Field(description="所有引用的原文片段（去重）")
    test_points: List[TestPointItem] = Field(description="测试点列表，通过 source_fragment_index 关联原文")
    coverage_analysis: str = Field(description="测试覆盖率分析")


class ReviewResult(BaseModel):
    is_approved: bool = Field(description="是否通过审批")
    completeness_score: float = Field(description="完整性评分 0-1")
    accuracy_score: float = Field(description="准确性评分 0-1")
    issues: List[str] = Field(default_factory=list, description="发现的问题")
    suggestions: List[str] = Field(default_factory=list, description="改进建议")
    missing_test_points: List[str] = Field(default_factory=list, description="遗漏的测试点")
