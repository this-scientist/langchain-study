import os
import sys
import uuid
import threading
import traceback
from typing import Dict, Optional, List
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))
from fastapi import FastAPI, UploadFile, File, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from graph.test_analysis_workflow import app as langgraph_app
from graph.test_analysis_workflow import run_with_user_interrupt, resume_after_user_review
from node.node_list import WordDocumentParser
from struct_output.output_list import DocSectionWithMetadata

UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "..", "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

app = FastAPI(title="测试点分析系统", version="2.0.0")

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


sessions: Dict[str, dict] = {}


class UserReviewInput(BaseModel):
    session_id: str
    user_input: str


class StartAnalysisInput(BaseModel):
    session_id: str
    selected_sections: List[int] = Field(default=[], description="选中的章节索引列表，为空则分析所有章节")


def run_analysis_in_thread(session_id: str, doc_path: str, selected_indices: List[int] = None):
    try:
        sessions[session_id]["status"] = "parsing"
        sessions[session_id]["progress"] = "正在解析Word文档..."
        sessions[session_id]["message"] = ""

        result, config = run_with_user_interrupt(doc_path, max_iterations=3, thread_id=session_id, selected_indices=selected_indices)

        sessions[session_id]["config"] = config

        if result:
            sessions[session_id]["status"] = "completed"
            sessions[session_id]["progress"] = "分析完成"
            sessions[session_id]["result"] = _serialize_result(result)
            sessions[session_id]["message"] = "分析完成"

            aggregated = result.get("aggregated_analysis")
            if aggregated:
                sessions[session_id]["aggregated_analysis"] = _to_dict(aggregated)
        else:
            sessions[session_id]["status"] = "awaiting_review"
            sessions[session_id]["progress"] = "等待用户审核"
            sessions[session_id]["message"] = "测试点分析已完成，请审核并输入意见"

            state = langgraph_app.get_state(config)
            if state:
                aggregated = state.values.get("aggregated_analysis")
                if aggregated:
                    sessions[session_id]["aggregated_analysis"] = _to_dict(aggregated)
                sessions[session_id]["approval_feedback"] = _serialize_approval(
                    state.values.get("approval_feedback")
                )

    except Exception as e:
        sessions[session_id]["status"] = "error"
        sessions[session_id]["progress"] = "分析出错"
        sessions[session_id]["message"] = f"{str(e)}\n{traceback.format_exc()}"


def _serialize_result(result: dict) -> dict:
    serialized = {}
    for key, value in result.items():
        if hasattr(value, "model_dump"):
            serialized[key] = value.model_dump()
        elif hasattr(value, "dict"):
            serialized[key] = value.dict()
        elif isinstance(value, list):
            serialized[key] = [_to_dict(v) for v in value]
        else:
            try:
                serialized[key] = str(value)
            except Exception:
                serialized[key] = None
    return serialized


def _to_dict(obj):
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    if hasattr(obj, "dict"):
        return obj.dict()
    if isinstance(obj, dict):
        return {k: _to_dict(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_to_dict(v) for v in obj]
    return str(obj)


def _serialize_approval(approval) -> Optional[dict]:
    if not approval:
        return None
    return _to_dict(approval)


@app.get("/api/health")
def health_check():
    return {"status": "ok"}


@app.post("/api/upload")
async def upload_file(file: UploadFile = File(...)):
    if not file.filename or not file.filename.endswith(".docx"):
        raise HTTPException(status_code=400, detail="仅支持 .docx 文件")

    session_id = str(uuid.uuid4())
    safe_filename = f"{session_id}.docx"
    file_path = os.path.join(UPLOAD_DIR, safe_filename)

    try:
        content = await file.read()
        if not content:
            raise HTTPException(status_code=400, detail="上传文件为空")
        with open(file_path, "wb") as f:
            f.write(content)

        parser = WordDocumentParser(file_path)
        parsed_data = parser.parse_section_3()

        if not parsed_data or not parsed_data.sections:
            raise HTTPException(status_code=400, detail="文档解析失败：未找到章节内容")

        toc = []
        for i, sec in enumerate(parsed_data.sections):
            toc.append({
                "index": i,
                "title": sec.title,
                "level": sec.level,
                "level_2": sec.metadata.level_2,
                "level_3": sec.metadata.level_3,
                "level_4": sec.metadata.level_4,
                "content_preview": sec.content[:200] + ("..." if len(sec.content) > 200 else ""),
                "has_tables": len(sec.tables) > 0,
                "function_types": [fs.section_type for fs in sec.function_sections],
            })

        sections_content = []
        for sec in parsed_data.sections:
            sections_content.append({
                "index": len(sections_content),
                "title": sec.title,
                "content": sec.content,
                "tables": [_table_to_dict(t) for t in sec.tables],
                "function_sections": [
                    {
                        "section_type": fs.section_type,
                        "content": fs.content,
                    }
                    for fs in sec.function_sections
                ],
            })

        sessions[session_id] = {
            "status": "uploaded",
            "progress": "文件已上传",
            "file_path": file_path,
            "file_name": file.filename,
            "result": None,
            "config": None,
            "aggregated_analysis": None,
            "approval_feedback": None,
            "message": "",
            "toc": toc,
            "sections_content": sections_content,
            "selected_sections": [],
        }

        return {
            "session_id": session_id,
            "file_name": file.filename,
            "status": "uploaded",
            "toc": toc,
            "total_sections": len(toc),
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"文档解析失败: {str(e)}"
        )


def _table_to_dict(table) -> dict:
    return {
        "headers": table.headers,
        "rows": table.rows,
        "caption": table.caption,
    }


@app.get("/api/document-preview/{session_id}")
def get_document_preview(session_id: str):
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="会话不存在")
    session = sessions[session_id]
    return {
        "session_id": session_id,
        "file_name": session["file_name"],
        "toc": session.get("toc", []),
        "sections_content": session.get("sections_content", []),
    }


@app.post("/api/start-analysis")
def start_analysis(input_data: StartAnalysisInput):
    session_id = input_data.session_id
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="会话不存在")

    session = sessions[session_id]
    if session["status"] not in ("uploaded", "error"):
        raise HTTPException(status_code=400, detail=f"当前状态不允许启动分析: {session['status']}")

    session["selected_sections"] = input_data.selected_sections or []
    session["status"] = "starting"
    session["progress"] = "正在启动分析..."
    session["message"] = ""

    thread = threading.Thread(
        target=run_analysis_in_thread,
        args=(session_id, session["file_path"]),
        kwargs={"selected_indices": input_data.selected_sections},
        daemon=True,
    )
    thread.start()

    return {"session_id": session_id, "status": "started"}


@app.get("/api/analysis-status/{session_id}")
def get_analysis_status(session_id: str):
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="会话不存在")

    session = sessions[session_id]
    return {
        "session_id": session_id,
        "status": session["status"],
        "progress": session["progress"],
        "message": session["message"],
        "has_result": session["result"] is not None,
        "has_aggregated": session["aggregated_analysis"] is not None,
    }


@app.get("/api/analysis-result/{session_id}")
def get_analysis_result(session_id: str):
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="会话不存在")

    session = sessions[session_id]
    return {
        "session_id": session_id,
        "status": session["status"],
        "result": session.get("result"),
        "aggregated_analysis": session.get("aggregated_analysis"),
        "approval_feedback": session.get("approval_feedback"),
    }


@app.post("/api/submit-review")
def submit_review(input_data: UserReviewInput):
    session_id = input_data.session_id
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="会话不存在")

    session = sessions[session_id]
    if session["status"] != "awaiting_review":
        raise HTTPException(status_code=400, detail=f"当前状态不允许审核: {session['status']}")

    config = session.get("config")
    if not config:
        raise HTTPException(status_code=500, detail="未找到流程状态")

    try:
        result = resume_after_user_review(config, input_data.user_input)

        session["status"] = "completed"
        session["progress"] = "分析完成"
        session["message"] = "审核完成，已生成最终结果"

        if result:
            session["result"] = _serialize_result(result)
            aggregated = result.get("aggregated_analysis")
            if aggregated:
                session["aggregated_analysis"] = _to_dict(aggregated)

        return {
            "session_id": session_id,
            "status": "completed",
            "result": session.get("result"),
            "aggregated_analysis": session.get("aggregated_analysis"),
        }
    except Exception as e:
        session["status"] = "error"
        session["message"] = f"恢复流程失败: {str(e)}"
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
