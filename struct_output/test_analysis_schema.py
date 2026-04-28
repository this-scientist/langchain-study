from pydantic import BaseModel, Field
from typing import List, Optional


class TestPointItem(BaseModel):
    test_point_id: str = Field(description="测试点业务唯一标识，如 TP-001")
    description: str = Field(description="测试点描述")
    priority: str = Field(default="中", description="优先级：高、中、低")
    test_type: str = Field(default="功能测试", description="测试类型：功能测试/边界测试/异常测试/权限测试等")
    steps: List[str] = Field(default_factory=list, description="测试步骤")
    expected_results: List[str] = Field(default_factory=list, description="预期结果")


class SinglePartAnalysisResult(BaseModel):
    test_points: List[TestPointItem] = Field(description="针对该需求片段生成的测试点列表")


class FormatReviewIssue(BaseModel):
    field: str = Field(description="有问题的字段名: steps / expected_results / priority / test_type")
    issue: str = Field(description="具体问题描述")
    suggestion: str = Field(description="改进建议")


class SingleTestPointReviewResult(BaseModel):
    test_point_id: str = Field(description="被审查的测试点业务ID")
    is_valid: bool = Field(description="是否合格")
    issues: List[FormatReviewIssue] = Field(default_factory=list, description="发现的问题列表")
