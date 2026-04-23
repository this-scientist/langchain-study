from pydantic import BaseModel, Field, List
# 1. 定义我们想要收集的信息模型
class IntentProgress(BaseModel):
    main_intent: str = Field(description="主意图，如：维修、投诉、查询")
    extracted_slots: dict = Field(description="从用户话语中提取的参数，如：{'设备': '冰箱'}")
    missing_info: str = Field(description="为了完成任务，还需要问用户的一个最关键问题。如果不需要提问则为空。")
    is_complete: bool = Field(description="所有必要信息是否已集齐")

class DocumentSection(BaseModel):
    """单条文档章节的结构"""
    title: str = Field(description="章节标题")
    level: int = Field(description="标题层级")
    content: str = Field(description="章节正文")

class ParsedDoc(BaseModel):
    """整份文档的解析结果"""
    sections: List[DocumentSection]
    summary_needed: bool = Field(default=True)