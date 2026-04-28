import os
import sys
import uuid
import threading
import traceback
import json
from typing import Dict, Optional, List, Any
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))
from fastapi import FastAPI, UploadFile, File, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from graph.test_analysis_workflow import app as langgraph_app, run_task_analysis
from node.node_list import WordDocumentParser
from prompt.test_analysis import REFLECTION_ANALYSIS_PROMPT
from node.test_analysis_nodes import _get_llm, _invoke_structured
from struct_output.test_analysis_schema import SinglePartAnalysisResult

UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "..", "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

app = FastAPI(title="测试点分析系统", version="3.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
os.makedirs(STATIC_DIR, exist_ok=True)

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
def serve_index():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


# 内存中仅保存运行中的任务进度，最终结果从数据库读取
sessions: Dict[str, dict] = {}


class StartAnalysisInput(BaseModel):
    task_id: str
    selected_part_ids: List[str] = Field(..., description="选中的需求片段ID列表")


def run_analysis_in_thread(task_id: str, doc_id: str, file_path: str, part_ids: List[str]):
    try:
        # 更新数据库任务状态
        db_manager.update_task_status(task_id, "running")
        
        # 启动 LangGraph 工作流
        # thread_id 使用 task_id
        config = {"configurable": {"thread_id": task_id}}
        
        # 在内存中记录状态，方便前端查询进度
        sessions[task_id] = {
            "status": "analyzing",
            "progress": "准备开始分析...",
            "message": "",
            "task_id": task_id,
            "doc_id": doc_id
        }

        # 执行工作流
        # 我们使用 stream 来获取中间进度更新（可选，这里先简单调用）
        result, _ = run_task_analysis(task_id, doc_id, file_path, part_ids, thread_id=task_id)

        # 任务完成
        db_manager.update_task_status(task_id, "completed")
        
        if task_id in sessions:
            sessions[task_id]["status"] = "completed"
            sessions[task_id]["progress"] = "分析完成"

    except Exception as e:
        error_msg = f"{str(e)}\n{traceback.format_exc()}"
        print(f"Error in analysis thread: {error_msg}")
        db_manager.update_task_status(task_id, "failed", error_message=str(e))
        
        if task_id in sessions:
            sessions[task_id]["status"] = "error"
            sessions[task_id]["progress"] = "分析出错"
            sessions[task_id]["message"] = str(e)


@app.get("/api/health")
def health_check():
    return {"status": "ok"}


@app.post("/api/upload")
async def upload_file(file: UploadFile = File(...)):
    if not file.filename or not file.filename.endswith(".docx"):
        raise HTTPException(status_code=400, detail="仅支持 .docx 文件")

    file_id = str(uuid.uuid4())
    safe_filename = f"{file_id}.docx"
    file_path = os.path.join(UPLOAD_DIR, safe_filename)

    try:
        content = await file.read()
        if not content:
            raise HTTPException(status_code=400, detail="上传文件为空")
        with open(file_path, "wb") as f:
            f.write(content)

        # 解析文档
        parser = WordDocumentParser(file_path)
        parsed_data = parser.parse_section_3()

        if not parsed_data or not parsed_data.sections:
            raise HTTPException(status_code=400, detail="文档解析失败：未找到章节内容")

        # 将解析后的文档及其片段保存到数据库
        doc_id = db_manager.save_parsed_document(file.filename, file_path, parsed_data)

        # 构造返回给前端的目录结构，包含片段 ID
        doc_info = db_manager.get_document(doc_id)
        
        toc = []
        for sec in doc_info['sections']:
            parts = []
            for part in sec['function_sections']:
                parts.append({
                    "id": part['id'],
                    "type": part['section_type'],
                    "content_preview": part['content'][:100] + "..." if len(part['content']) > 100 else part['content']
                })
            
            toc.append({
                "id": sec['id'],
                "title": sec['title'],
                "level": sec['level'],
                "parts": parts
            })

        return {
            "doc_id": doc_id,
            "file_name": file.filename,
            "status": "uploaded",
            "toc": toc
        }

    except Exception as e:
        print(traceback.format_exc())
        raise HTTPException(
            status_code=500,
            detail=f"文档解析失败: {str(e)}"
        )


@app.get("/api/document/{doc_id}")
def get_document(doc_id: str):
    doc = db_manager.get_document(doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="文档不存在")
    return doc


@app.post("/api/create-task")
def create_task(doc_id: str = Query(...)):
    """为文档创建一个新的分析任务"""
    task_id = db_manager.create_analysis_task(doc_id, [])
    return {"task_id": task_id}


@app.post("/api/start-analysis")
def start_analysis(input_data: StartAnalysisInput):
    task_id = input_data.task_id
    part_ids = input_data.selected_part_ids
    
    if not part_ids:
        raise HTTPException(status_code=400, detail="请选择至少一个需求片段进行分析")

    # 获取第一个片段的信息来确定文档路径
    first_part = db_manager.get_function_part(part_ids[0])
    if not first_part:
        raise HTTPException(status_code=404, detail="需求片段不存在")
    
    doc_id = first_part["doc_id"]
    file_path = first_part["file_path"]

    # 启动后台线程执行分析
    thread = threading.Thread(
        target=run_analysis_in_thread,
        args=(task_id, doc_id, file_path, part_ids),
        daemon=True,
    )
    thread.start()

    return {"task_id": task_id, "status": "started"}


@app.get("/api/task-status/{task_id}")
def get_task_status(task_id: str):
    # 优先从内存获取进度信息
    if task_id in sessions:
        return sessions[task_id]
    
    # 从数据库获取
    task = db_manager.get_task(task_id)
    if task:
        return {
            "task_id": task_id,
            "status": task["status"],
            "progress": "已完成" if task["status"] == "completed" else "未在运行",
            "message": task.get("error_message") or ""
        }

    raise HTTPException(status_code=404, detail="任务不存在")


@app.get("/api/task-results/{task_id}")
def get_task_results(task_id: str):
    """获取任务生成的测试点"""
    results = db_manager.get_analysis_results(task_id)
    # results 已经通过视图 v_task_test_points 关联了原文
    return {
        "task_id": task_id,
        "test_points": results
    }


@app.post("/api/stop-analysis/{task_id}")
def stop_analysis(task_id: str):
    if task_id in sessions:
        # 这里简单标记一下，实际 Graph 节点需要检查 state.is_cancelled
        sessions[task_id]["is_cancelled"] = True
        # 同时更新数据库
        db_manager.update_task_status(task_id, "cancelled")
        return {"status": "cancelling"}
    
    return {"status": "not_running"}


# 移除旧的 review 接口，因为新流程不需要


class RegenerateInput(BaseModel):
    task_id: str
    part_id: str
    user_feedback: str = Field(..., description="用户的批注/反馈意见")


@app.post("/api/regenerate-analysis")
async def regenerate_analysis(input_data: RegenerateInput):
    """
    针对特定片段的反思性重新生成。
    输入：用户反馈、原始测试点概要、原文。
    """
    task_id = input_data.task_id
    part_id = input_data.part_id
    feedback = input_data.user_feedback

    # 1. 获取原文内容
    part_data = db_manager.get_function_part(part_id)
    if not part_data:
        raise HTTPException(status_code=404, detail="片段不存在")
    content = part_data["content"]

    # 2. 获取该片段已有的测试点（仅获取 ID 和描述）
    old_points = db_manager.get_test_points_by_part_id(task_id, part_id)
    points_summary = "\n".join([f"- {p['test_point_id']}: {p['description']}" for p in old_points]) if old_points else "无原始测试点"

    # 3. 调用反思重新生成提示词
    from langchain.prompts import PromptTemplate
    prompt_tpl = PromptTemplate.from_template(REFLECTION_ANALYSIS_PROMPT)
    prompt_text = prompt_tpl.format(
        content=content,
        user_feedback=feedback,
        original_points=points_summary
    )

    try:
        # 4. 调用 LLM
        llm = _get_llm(0.3) # 重新生成建议适中温度
        result = _invoke_structured(llm, prompt_text, SinglePartAnalysisResult)

        # 5. 清理旧数据并保存新数据
        db_manager.delete_test_points_by_part_id(task_id, part_id)
        
        saved_tp_ids = []
        for tp in result.test_points:
            tp_id = db_manager.save_test_point(task_id, part_id, tp)
            saved_tp_ids.append(tp_id)

        return {
            "status": "success",
            "task_id": task_id,
            "part_id": part_id,
            "new_test_point_ids": saved_tp_ids
        }
    except Exception as e:
        print(f"重新生成失败: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"重新生成失败: {str(e)}")
