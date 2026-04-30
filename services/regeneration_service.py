"""消费 regeneration_jobs：对选中测试点软删旧版并写入新版。"""
import json
import traceback
from typing import Any, Dict, List

from struct_output.test_analysis_schema import SinglePartAnalysisResult

from db import db_manager
from prompt.test_analysis.regenerate_feedback import REGENERATE_WITH_FEEDBACK_PROMPT
from services.llm_structured import invoke_structured


def _row_to_public_dict(row: Dict[str, Any]) -> Dict[str, Any]:
    """供 Prompt 使用的当前测试点摘要（可序列化）。"""
    keys = (
        "test_point_id",
        "description",
        "priority",
        "test_type",
        "case_nature",
        "steps",
        "expected_results",
        "transaction_name",
        "test_case_path",
    )
    out: Dict[str, Any] = {}
    for k in keys:
        v = row.get(k)
        if k in ("steps", "expected_results") and isinstance(v, str):
            try:
                v = json.loads(v)
            except json.JSONDecodeError:
                pass
        out[k] = v
    return out


def run_regeneration_job(job_id: str) -> None:
    repo = db_manager.regeneration_jobs_repo
    tpr = db_manager.test_points_repo

    if not repo.mark_running(job_id):
        return

    try:
        job = repo.get_job(job_id)
        if not job:
            repo.mark_failed(job_id, "job not found")
            return

        task_id = str(job["task_id"])
        payload = job["payload"]
        if isinstance(payload, str):
            payload = json.loads(payload)

        ids: List[str] = list(payload.get("test_point_ids") or [])
        user_instruction = (payload.get("user_instruction") or "").strip() or "请优化本用例的可执行性与预期可验证性。"

        total = len(ids)
        if total == 0:
            repo.mark_completed(job_id)
            return

        for done, tp_id in enumerate(ids, start=1):
            row = tpr.get_active_for_task(tp_id, task_id)
            if not row:
                repo.update_progress(
                    job_id,
                    {"done": done, "total": total, "message": f"跳过不存在或已删除: {tp_id}"},
                )
                continue

            part_type = row.get("part_section_type") or ""
            part_content = (row.get("part_content") or "")[:12000]
            current_json = json.dumps(
                _row_to_public_dict(row), ensure_ascii=False, indent=2
            )

            prompt = REGENERATE_WITH_FEEDBACK_PROMPT.format(
                user_instruction=user_instruction,
                part_section_type=part_type,
                part_content=part_content,
                current_tp_json=current_json,
            )

            result = invoke_structured(prompt, SinglePartAnalysisResult)

            fid = str(row["function_part_id"])
            txn = row.get("transaction_name")
            tcp = row.get("test_case_path")

            n = tpr.soft_delete(tp_id, task_id)
            if n == 0:
                repo.update_progress(
                    job_id,
                    {"done": done, "total": total, "message": f"软删失败跳过: {tp_id}"},
                )
                continue

            for tp in result.test_points:
                db_manager.save_test_point(
                    task_id,
                    fid,
                    tp,
                    txn,
                    tcp,
                    replaces_id=tp_id,
                    regeneration_job_id=job_id,
                    user_feedback_at_regenerate=user_instruction,
                )

            repo.update_progress(
                job_id,
                {
                    "done": done,
                    "total": total,
                    "message": f"已处理 {done}/{total}",
                },
            )

        repo.mark_completed(job_id)
    except Exception as e:
        repo.mark_failed(job_id, f"{e}\n{traceback.format_exc()}")
