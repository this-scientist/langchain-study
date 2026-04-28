from pydantic import BaseModel, Field
from typing import List, Optional

# 表格数据模型
class TableData(BaseModel):
    headers: List[str] = Field(description="表格列标题")
    rows: List[List[str]] = Field(description="表格数据行")
    caption: Optional[str] = Field(default=None, description="表格标题/说明")

# 文档章节元数据模型
class DocSectionMetadata(BaseModel):
    level_1: str = Field(description="一级标题")
    level_2: str = Field(description="二级标题")
    level_3: str = Field(description="三级标题")
    level_4: Optional[str] = Field(default=None, description="四级标题")

# 功能部分模型
class FunctionSection(BaseModel):
    section_type: str = Field(description="部分类型：功能描述、业务规则、操作权限、处理过程、异常处理等")
    content: str = Field(description="该部分的详细内容")
    tables: List[TableData] = Field(default_factory=list, description="该部分包含的表格")

# 带元数据的文档章节模型
class DocSectionWithMetadata(BaseModel):
    title: str = Field(description="完整标题")
    level: int = Field(description="标题层级")
    content: str = Field(description="章节正文内容")
    metadata: DocSectionMetadata = Field(description="层级元数据")
    function_sections: List[FunctionSection] = Field(default_factory=list, description="功能分解部分")
    tables: List[TableData] = Field(default_factory=list, description="章节内的所有表格")

# 带元数据的解析文档模型
class ParsedDocWithMetadata(BaseModel):
    sections: List[DocSectionWithMetadata] = Field(description="解析后的章节列表")
    total_count: int = Field(description="总章节数")
