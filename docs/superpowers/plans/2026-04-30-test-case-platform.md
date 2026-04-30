# 测试用例平台（PostgreSQL + 重生成）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在仅 PostgreSQL 验收前提下，落地规格文档中的表结构、仓储与 API、首跑 LangGraph 节点去 SQLite 化、RegenerationService + `regeneration_jobs`、前端联调与导出过滤，使「上传 → 分析 → 筛选/软删 → 重生成 → 导出当前版本」全链路可测。

**Architecture:** `DatabaseManager` 之上增加按域划分的 Repository（或等价方法模块）；`node/test_analysis_nodes.py` 仅通过仓储访问 PG；首跑仍用 `graph/test_analysis_workflow.py`；重跑由 `services/regeneration_service.py` + 后台线程消费 `regeneration_jobs`；LLM 调用与 JSON 结构化解析抽到 `services/llm_structured.py` 供首跑节点与重跑共用。

**Tech stack:** FastAPI, LangGraph, psycopg2, PostgreSQL 13+, python-docx, 现有 GLM 兼容 OpenAI 客户端；测试用 pytest；可选 Docker Compose 起 PG。

**规格依据:** `docs/superpowers/specs/2026-04-30-test-case-platform-design.md`

---

## 文件结构总览（实现前锁定）

| 路径 | 职责 |
|------|------|
| `sql/schema.sql` | 新库全量建表；含 `regeneration_jobs`、`test_points` 新列、`analysis_tasks.selected_part_ids` |
| `sql/migrations/001_selected_part_ids_and_regeneration.sql` | 已有库增量 ALTER（不重跑整份 DROP） |
| `db/database.py` | 保留连接配置；逐步迁出大方法到 repositories 或保留为门面 |
| `db/repositories/__init__.py` | 导出仓储类 |
| `db/repositories/tasks.py` | `create_task`, `update_task_status`, `set_selected_part_ids`, `get_task` |
| `db/repositories/test_points.py` | `list_by_task`, `soft_delete`, `insert_after_regenerate`, `get_for_regeneration` |
| `db/repositories/regeneration_jobs.py` | `create_job`, `get_job`, `update_progress`, `mark_running/completed/failed` |
| `db/repositories/documents.py` | `get_function_part`, `get_section_table`, `get_section_table_ids_by_part_ids`, `fetch_section_content`（供 prepare） |
| `services/llm_structured.py` | `_get_llm`, `invoke_structured_json`（从 `node/test_analysis_nodes.py` 抽出） |
| `services/regeneration_service.py` | `run_regeneration_job(job_id: str) -> None` |
| `node/test_analysis_nodes.py` | 调用 repositories + `llm_structured`，无裸 SQL |
| `graph/test_analysis_workflow.py` | 入口不变；`run_task_analysis` 仍 `invoke` |
| `backend/main.py` | 路由对齐规格 §4；线程启动首跑与 job |
| `backend/static/frontend/js/api.js` | 全端点 + 统一 `API_BASE` |
| `backend/static/frontend/js/task-manager.js` / `pages/analysis.html` | 创建任务、start-analysis、重生成 UI、轮询 job |
| `frontend/` | 与 static 同步拷贝或 README 说明单一源 |
| `tests/conftest.py` | PG 连接 fixture（环境变量） |
| `tests/test_regeneration_flow.py` | 集成：建任务 stub + mock LLM 或真实小调用 |
| `docker-compose.yml`（可选） | `postgres:15` + 端口映射 |

---

### Task 1: 数据库 DDL（全量 + 增量）

**Files:**
- Modify: `sql/schema.sql`（`analysis_tasks` 列名、`test_points` 新列、`regeneration_jobs` 新表）
- Create: `sql/migrations/001_selected_part_ids_and_regeneration.sql`
- Test: `tests/test_schema_migration_applies.py`（对空库执行 schema 无语法错误；或对测试库跑 migration）

- [ ] **Step 1: 编写失败测试（迁移在测试库可执行）**

```python
# tests/test_schema_migration_applies.py
import os
import psycopg2

def test_migration_sql_file_exists():
    root = os.path.join(os.path.dirname(__file__), "..", "sql", "migrations", "001_selected_part_ids_and_regeneration.sql")
    assert os.path.isfile(root), f"missing {root}"
```

- [ ] **Step 2: 运行测试确认失败（若文件未创建）**

Run: `pytest tests/test_schema_migration_applies.py::test_migration_sql_file_exists -v`  
Expected: FAIL until migration file exists.

- [ ] **Step 3: 更新 `sql/schema.sql` 片段（手工合并到现有 DROP/CREATE 顺序）**

在 `DROP TABLE` 列表中加入 `regeneration_jobs`（在 `test_points` 之前 drop 若 FK 从 test_points 指向 jobs，则先 drop test_points 或先 drop FK——推荐：**先 drop test_points 再 analysis_tasks** 前加 `regeneration_jobs`，因 `test_points.regeneration_job_id` FK 到 `regeneration_jobs`，故 **创建顺序**：`regeneration_jobs` 在 `test_points` 之前创建；**删除顺序**：先 `test_points` 再 `regeneration_jobs` 或先删 FK。最简单：**`regeneration_jobs` 不被 `test_points` FK**（规格要求 FK）则创建顺序：`analysis_tasks` → `regeneration_jobs` → `test_points` 中 FK 到 `regeneration_jobs`。PostgreSQL 要求被引用表先存在，故：

```sql
-- 在 analysis_tasks 之后、test_points 之前增加：

CREATE TABLE regeneration_jobs (
    id                    UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    task_id               UUID    NOT NULL REFERENCES analysis_tasks(id) ON DELETE CASCADE,
    status                TEXT    NOT NULL DEFAULT 'pending',
    payload               JSONB   NOT NULL,
    progress              JSONB,
    error_message         TEXT,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at            TIMESTAMPTZ,
    completed_at          TIMESTAMPTZ
);

CREATE INDEX idx_regen_task ON regeneration_jobs(task_id, created_at DESC);
CREATE INDEX idx_regen_status ON regeneration_jobs(status);
```

在 `test_points` 表定义中增加：

```sql
    replaces_id                  UUID REFERENCES test_points(id) ON DELETE SET NULL,
    regeneration_job_id          UUID REFERENCES regeneration_jobs(id) ON DELETE SET NULL,
    user_feedback_at_regenerate  TEXT,
```

将 `analysis_tasks` 中 `selected_section_ids` 重命名为：

```sql
    selected_part_ids  JSONB   NOT NULL DEFAULT '[]',
```

并更新注释为「`section_function_parts.id` 的 UUID 数组」。

- [ ] **Step 4: 编写增量迁移 `sql/migrations/001_selected_part_ids_and_regeneration.sql`**

```sql
-- 001: 已有库升级（按实际列名调整顺序）
BEGIN;

ALTER TABLE analysis_tasks RENAME COLUMN selected_section_ids TO selected_part_ids;

CREATE TABLE IF NOT EXISTS regeneration_jobs (
    id                    UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    task_id               UUID    NOT NULL REFERENCES analysis_tasks(id) ON DELETE CASCADE,
    status                TEXT    NOT NULL DEFAULT 'pending',
    payload               JSONB   NOT NULL,
    progress              JSONB,
    error_message         TEXT,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at            TIMESTAMPTZ,
    completed_at          TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_regen_task ON regeneration_jobs(task_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_regen_status ON regeneration_jobs(status);

ALTER TABLE test_points ADD COLUMN IF NOT EXISTS replaces_id UUID REFERENCES test_points(id) ON DELETE SET NULL;
ALTER TABLE test_points ADD COLUMN IF NOT EXISTS regeneration_job_id UUID REFERENCES regeneration_jobs(id) ON DELETE SET NULL;
ALTER TABLE test_points ADD COLUMN IF NOT EXISTS user_feedback_at_regenerate TEXT;

COMMIT;
```

- [ ] **Step 5: 运行测试**

Run: `pytest tests/test_schema_migration_applies.py -v`  
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add sql/schema.sql sql/migrations/001_selected_part_ids_and_regeneration.sql tests/test_schema_migration_applies.py
git commit -m "feat(db): regeneration_jobs, test_points lineage, selected_part_ids"
```

---

### Task 2: `DatabaseManager` 与 `selected_part_ids` 语义

**Files:**
- Modify: `db/database.py`（`create_analysis_task` 参数改为 `List[str]` part UUIDs；SQL 列名 `selected_part_ids`；所有读 `selected_section_ids` 处改名）
- Modify: `backend/main.py`（调用 `create_analysis_task` 时传 part ids）
- Test: `tests/test_task_repository_contract.py`

- [ ] **Step 1: 写失败单测**

```python
# tests/test_task_repository_contract.py
from db.database import DatabaseManager

def test_create_task_accepts_uuid_strings(monkeypatch):
    # 若无真实 PG，用 monkeypatch mock get_connection；有则用 env TEST_DATABASE_URL
    ...
```

实现时用 **真实 PG** 或 **mock cursor**：计划执行者二选一；若有 `TEST_DATABASE_URL`，测试插入再 rollback。

- [ ] **Step 2: 修改 `create_analysis_task` 签名与 SQL**

```python
def create_analysis_task(self, document_id: str, selected_part_ids: List[str]) -> str:
    task_id = str(uuid.uuid4())
    cur.execute(
        "INSERT INTO analysis_tasks (id, document_id, selected_part_ids, status) VALUES (%s, %s, %s, %s)",
        (task_id, document_id, json.dumps(selected_part_ids), 'pending'),
    )
```

- [ ] **Step 3: 运行测试** → **Step 4: Commit** `git commit -m "refactor(db): analysis_tasks.selected_part_ids UUID list"`

---

### Task 3: 仓储模块骨架（无业务逻辑）

**Files:**
- Create: `db/repositories/__init__.py`
- Create: `db/repositories/documents.py`（从 `database.py` 剪切 `get_function_part`, `get_section_table`, `get_section_table_ids_by_part_ids` 并改为类方法或模块函数，**占位符全 `%s`**）
- Create: `db/repositories/test_points.py`
- Create: `db/repositories/regeneration_jobs.py`
- Modify: `db/database.py`（委托到 repositories 或保持薄包装）
- Test: `tests/test_repositories_import.py`（`import db.repositories.documents` 不报错）

- [ ] **Step 1:** `pytest tests/test_repositories_import.py -v` 先红后绿  
- [ ] **Step 2:** Commit `feat(db): add repository package skeleton`

---

### Task 4: 抽出 `services/llm_structured.py`

**Files:**
- Create: `services/__init__.py`
- Create: `services/llm_structured.py`
- Modify: `node/test_analysis_nodes.py`（删除重复 LLM 代码，改为 `from services.llm_structured import invoke_structured`）
- Test: `tests/test_llm_structured_skips_without_key.py`（无 API key 时 skip 或 mock `ChatOpenAI.invoke`）

```python
# services/llm_structured.py（核心签名）
def invoke_structured(prompt_text: str, output_cls: type[BaseModel]) -> BaseModel:
    ...
```

- [ ] Commit: `refactor(llm): shared invoke_structured for nodes and regeneration`

---

### Task 5: 改写 `prepare_data_node` / `single_analysis_node` / `rule_analysis_node` 仅走 PG 仓储

**Files:**
- Modify: `node/test_analysis_nodes.py`
- 将所有 `conn.execute("...?", ...)` 改为 `documents_repo.fetch_section_content(section_id)` 等，使用 `%s` 在 repository 内。

**关键行为保持不变：** `fan_out_to_analyses` 依赖的 state 键名不变。

- [ ] **Step 1:** 本地起 PG，跑一遍上传+小任务（手工或 pytest integration）  
- [ ] **Step 2:** Commit `fix(nodes): PostgreSQL-only queries via repositories`

---

### Task 6: `RegenerationService`

**Files:**
- Create: `services/regeneration_service.py`
- Modify: `db/repositories/test_points.py`（实现 `soft_delete_by_ids`, `insert_regenerated_rows`）
- Modify: `db/repositories/regeneration_jobs.py`

**核心逻辑 `run_regeneration_job(job_id)`：**

1. `SELECT ... FROM regeneration_jobs WHERE id = %s FOR UPDATE SKIP LOCKED`（或简单 `UPDATE status='running' WHERE id=%s AND status='pending'` 返回 rowcount）。
2. 解析 `payload`：`test_point_ids`, `user_instruction`。
3. 对每个 id：加载旧测试点 + `function_part_id` 关联内容；拼 Prompt（新模板 `prompt/test_analysis/regenerate_from_test_point.py` 或内联字符串）；`invoke_structured(..., SinglePartAnalysisResult)`。
4. 每条：软删旧行 → 插入新行（`replaces_id`, `regeneration_job_id`, `user_feedback_at_regenerate`）。
5. 更新 `progress` JSON：`{"done": i, "total": n, "message": "..."}`。
6. 完成：`status=completed`, `completed_at=now()`；异常：`status=failed`, `error_message`。

- [ ] **Step 1: 单测 mock LLM**

```python
# tests/test_regeneration_service_db.py
def test_regeneration_marks_old_deleted(monkeypatch, db_conn):
    # 插入 document/section/part/task/test_point，再创建 job，mock invoke_structured 返回固定 SinglePartAnalysisResult
    ...
```

- [ ] **Step 2: Commit** `feat(regen): RegenerationService + job progress`

---

### Task 7: FastAPI 路由（规格 §4）

**Files:**
- Modify: `backend/main.py`

**必须实现的路由（与规格一致或等价别名）：**

- `POST /api/tasks` — body: `{"document_id": "<uuid>"}` → `create_analysis_task(doc_id, [])` 返回 `task_id`。
- `POST /api/tasks/{task_id}/start-analysis` — body: `{"selected_part_ids": [...]}` → 更新 `selected_part_ids`、`status=running`、启动线程调用现有 `run_task_analysis`（**删除** `POST /api/start-analysis` 或内部 307 重定向到新路径，避免双 INSERT）。
- `GET /api/tasks/{task_id}/test-points?limit=&offset=` — 仅 `is_deleted=false`。
- `PATCH /api/test-points/{id}` — body `{"is_deleted": true}`。
- `POST /api/tasks/{task_id}/regenerate-test-points` — 创建 `regeneration_jobs`，`threading.Thread(target=run_regeneration_job, args=(job_id,), daemon=True).start()`，返回 `{"job_id": ...}`。
- `GET /api/regeneration-jobs/{job_id}` — 返回 job 行 JSON。
- `GET /api/export-test-points?task_id=<uuid>&include_deleted=false` — 仅该任务未删除行。
- `GET /api/task-status/{task_id}` — 读 `analysis_tasks`；若存在 `status=running` 的 regeneration_job 可附加字段 `regeneration: {job_id, progress}`。

- [ ] **Step 1:** 用 `httpx.AsyncClient(app=app)` 写 `tests/test_api_routes_smoke.py` 对无 DB 时 503 或 skip  
- [ ] **Step 2:** Commit `feat(api): tasks start-analysis test-points regenerate export`

---

### Task 8: 移除业务路径对 `DB_MODE=local` 的依赖

**Files:**
- Modify: `db/__init__.py` — 默认仅导出 `DatabaseManager`；若保留 `local` 则仅用于 **离线开发** 且 `README.md` 标明「规格验收不包含 SQLite」。
- Modify: `README.md` — 启动前必须 `DB_*` 与 `sql/schema.sql`。

- [ ] Commit `docs: PostgreSQL-only runtime for spec compliance`

---

### Task 9: 前端（`backend/static/frontend`）

**Files:**
- Modify: `backend/static/frontend/js/api.js` — 方法：`createTask(documentId)`, `startAnalysis(taskId, partIds)`, `listTestPoints(taskId, ...)`, `patchTestPoint(id, body)`, `regenerateTestPoints(taskId, ids, instruction)`, `getRegenerationJob(jobId)`, `exportTestPoints(taskId)`。
- Modify: `backend/static/frontend/pages/analysis.html` + 对应 JS：多选 checkbox、软删、Modal 输入 `user_instruction`、轮询 `getRegenerationJob` 每 1.5s 直至 terminal 状态。
- 将同 diff **同步**到 `frontend/` 或删除重复目录之一并在 README 写死。

- [ ] Commit `feat(frontend): regenerate flow and export by task_id`

---

### Task 10: 性能（首跑并发上限）

**Files:**
- Modify: `node/test_analysis_nodes.py` 或 `services/llm_structured.py`

在 `invoke_structured` 或节点外层使用 **全局 `threading.BoundedSemaphore(3)`**（首版简单可测），防止同时 10+ LLM 请求。

- [ ] Commit `perf(llm): cap concurrent structured invocations`

---

### Task 11: Docker Compose + CI 说明

**Files:**
- Create: `docker-compose.yml`

```yaml
services:
  postgres:
    image: postgres:15
    environment:
      POSTGRES_USER: test
      POSTGRES_PASSWORD: test
      POSTGRES_DB: langchain_test
    ports:
      - "5433:5432"
```

- [ ] **README 片段**：`docker compose up -d` → `export DB_HOST=127.0.0.1 DB_PORT=5433 ...` → `psql ... -f sql/schema.sql`

- [ ] Commit `chore: docker-compose for local PostgreSQL`

---

## Spec 覆盖自检

| 规格章节 | 对应 Task |
|----------|-----------|
| §2.1 test_points 列 | Task 1 |
| §2.2 selected_part_ids | Task 1–2 |
| §2.3 regeneration_jobs | Task 1, 6, 7 |
| §3 State/SQL | Task 5, 8 |
| §4 API | Task 7 |
| §5 LangGraph + 性能 | Task 5, 10 |
| §5.2 RegenerationService | Task 6 |
| §6 前端 | Task 9 |
| §7 测试 | Task 1–2, 6, 7 |

无占位符：本计划未使用 TBD；测试步骤在 Task 1/6/7 给出具体文件名。

---

## 执行交接

**计划已保存到** `docs/superpowers/plans/2026-04-30-test-case-platform.md`。

**两种执行方式：**

1. **Subagent-Driven（推荐）** — 每个 Task 派生子代理，任务间人工/你复核，迭代快。  
2. **Inline Execution** — 本会话按 Task 顺序执行，每 2–3 个 Task 设检查点。

**你更倾向哪一种？**（回复 `1` 或 `2`；若不回复，默认按 **2** 在本会话继续实现。）

下一步我将把该计划文件提交到 git（若你尚未提交）。
