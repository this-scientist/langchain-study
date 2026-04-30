# 测试用例平台：PostgreSQL 优先 + 重生成与导出 — 设计规格

**日期**：2026-04-30  
**状态**：已定稿（待实现前评审）  
**范围**：数据库与 state 边界、首跑与重跑、API、前端单一发布源、性能策略、验收标准。

---

## 1. 背景与目标

### 1.1 业务主流程

用户：**创建任务 → 上传文档 → 大模型生成用例 → 筛选 / 删除 → 导出**；并支持对**已选用例**触发**重新生成**（带用户优化说明，类似反思），且导出**仅包含当前有效版本**。

### 1.2 已确认的决策

| 项 | 决策 |
|----|------|
| 数据库验收标准 | **仅 PostgreSQL**（`sql/schema.sql` 为权威）；SQLite 不作为本轮对齐目标 |
| 重生成落库语义 | **A**：旧测试点 **软删除**（`is_deleted=true`），**插入新行**；导出只含 `is_deleted=false` |
| 重跑任务编排 | **第一版即包含** `regeneration_jobs` 表（见第 3 节），支持状态追踪与后续扩展队列 |

### 1.3 架构取向（相对未选方案）

采用 **「统一仓储层 + 首跑保留 LangGraph、重跑走 RegenerationService」**：

- 首跑：保留 `prepare_data` + `Send` 并发，但所有持久化与读库经 **PostgreSQL Repository**。
- 重跑：FastAPI 创建 `regeneration_jobs` 记录后，由后台线程/worker 执行 **RegenerationService**（非必须再走完整 LangGraph），降低延迟与心智负担。
- 共用的 **Prompt 构建、LLM 调用、结构化解析** 抽到独立模块，避免首跑/重跑重复实现。

---

## 2. 数据模型（PostgreSQL）

### 2.1 `test_points` 增量

在现有 `sql/schema.sql` 中 `test_points` 定义基础上增加（名称可微调，语义如下）：

| 列名 | 类型 | 说明 |
|------|------|------|
| `replaces_id` | UUID NULL FK → `test_points(id)` | 本条记录取代的**上一版**主键；首版生成可为 NULL |
| `regeneration_job_id` | UUID NULL FK → `regeneration_jobs(id)` | 若由重跑任务产生则填写；首跑可为 NULL |
| `user_feedback_at_regenerate` | TEXT NULL | 产生本条时用户提交的优化说明（审计）；首跑为 NULL |

**不变约束**：列表、详情、导出统一默认条件 **`is_deleted = false`**。

**重生成写库顺序**（单条或批量内对每条）：

1. 将当前有效行 `is_deleted = true`（WHERE `id` IN 用户选中且 `is_deleted=false`）。
2. INSERT 新行：`is_deleted=false`，`replaces_id` = 旧行 `id`，`regeneration_job_id` = 当前 job，`user_feedback_at_regenerate` = 本次说明。

### 2.2 `analysis_tasks` 语义澄清

- **`selected_section_ids`（现有 JSONB）**：本设计规定**弃用「章节整数索引」混用**，改为存 **`selected_part_ids: UUID[]`**（功能片段 `section_function_parts.id`）。  
  - **迁移**：在 `schema.sql` 与迁移脚本中可将列重命名为 `selected_part_ids`，或保留列名但文档与代码统一只写 UUID 数组；**禁止**再写入章节 index。
- **`status`**：`pending` | `running` | `completed` | `failed` | `cancelled`；与 `regeneration_jobs.status` 独立。

### 2.3 `regeneration_jobs`（第一版必选）

新建表：

| 列名 | 类型 | 说明 |
|------|------|------|
| `id` | UUID PK | |
| `task_id` | UUID NOT NULL FK → `analysis_tasks(id)` | 所属分析任务 |
| `status` | TEXT NOT NULL | `pending` → `running` → `completed` \| `failed` |
| `payload` | JSONB NOT NULL | 如 `{"test_point_ids": ["uuid", ...], "user_instruction": "string"}` |
| `progress` | JSONB NULL | 如 `{"done": 3, "total": 10, "message": "..."}` |
| `error_message` | TEXT NULL | 失败时 |
| `created_at` | TIMESTAMPTZ | |
| `updated_at` | TIMESTAMPTZ | |
| `started_at` | TIMESTAMPTZ NULL | |
| `completed_at` | TIMESTAMPTZ NULL | |

**索引**：`(task_id, created_at DESC)`、`(status)`。

**与 API 关系**：`POST /api/tasks/{task_id}/regenerate-test-points` 创建一行 `regeneration_jobs`（`pending`），异步 worker 置 `running`，逐条处理并更新 `progress`，结束置 `completed`/`failed`。

---

## 3. State 与 SQL 边界

### 3.1 `DocState`（首跑）

仅包含：**任务与文档指针、选中片段 ID 列表、预处理得到的分类字段、取消标记、短进度文案**。禁止承载整章正文；正文与表格在节点内通过 **Repository** 按 ID 查询。

### 3.2 节点与 SQL

- **唯一 SQL 方言**：`psycopg2`，占位符 **`%s`**。
- **禁止**在 `node/` 中直接 `open` 连接字符串拼接；统一经 `DatabaseManager` 或薄封装 `Repository` 类（按聚合根划分：`DocumentRepository`, `TestPointRepository`, `TaskRepository`, `RegenerationRepository` 等，可按实现合并文件数）。

### 3.3 配置

- 移除或旁路 **`DB_MODE` 分支**在业务代码中的依赖；运行与 CI **仅针对 PostgreSQL**。

---

## 4. API 契约（与前端对齐）

以下路径为设计目标；实现时可微调动词，但语义需一致。

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/upload` | 上传 docx，解析入库，返回 `doc_id` + `toc` |
| POST | `/api/tasks` | 创建任务（body 含 `document_id`，可选元数据） |
| POST | `/api/tasks/{task_id}/start-analysis` | body：`{ "selected_part_ids": [...] }`；**唯一**写入首跑 `analysis_tasks` 运行态并启动 LangGraph 的入口（避免与 upload 内重复建任务） |
| GET | `/api/tasks` | 任务列表 |
| GET | `/api/tasks/{task_id}` | 任务详情 |
| GET | `/api/tasks/{task_id}/test-points` | 分页查询当前有效测试点（`is_deleted=false`） |
| PATCH | `/api/test-points/{id}` | 软删：`{"is_deleted": true}` 等 |
| POST | `/api/tasks/{task_id}/regenerate-test-points` | body：`{ "test_point_ids": [...], "user_instruction": "..." }`；返回 `{ "job_id": "..." }` |
| GET | `/api/regeneration-jobs/{job_id}` | 查询 job 状态与 `progress` |
| GET | `/api/export-test-points` | Query：`task_id`（必填或二选一）、`include_deleted=false`（默认）；**仅导出当前版本** |
| GET | `/api/task-status/{task_id}` | 以**数据库**为准返回首跑任务状态；可选合并「该 task 下最新 running 的 regeneration_job」摘要 |

**弃用/合并**：现有 `POST /api/start-analysis` 与手写 `INSERT analysis_tasks` 应合并为上述 `start-analysis` 单一路径，避免重复插入。

---

## 5. LangGraph 与性能

### 5.1 首跑

- 保留 `StateGraph` + `fan_out_to_analyses` + `Send`。
- LLM 调用：**有上限的并发**（如 `asyncio.Semaphore` + 线程池或 httpx async），防止瞬时打满供应商限流。
- Prompt：**Token 预算**（规则正文、表格 Markdown 超长截断策略）写入实现注释与 README。

### 5.2 重跑（RegenerationService）

- 输入：`job.payload` 中的 `test_point_ids`、`user_instruction`。
- 对每条（或可批量若 prompt 允许）：加载**旧用例结构化字段 + 关联 function_part / 表格上下文 + user_instruction**，调用与首跑共用的结构化输出 schema，然后执行 **软删旧 + 插入新**（见 §2.1）。
- 更新 `regeneration_jobs.progress` 与最终 `status`。

---

## 6. 前端

- **唯一发布目录**：`backend/static/frontend`；根目录 `frontend/` 作为源时需在 README 写明同步命令（或构建脚本拷贝），避免双份漂移。
- **`api.js`**：封装 §4 所有端点；**统一 `API_BASE`**（与页面部署同源或显式配置）。
- **分析页**：多选测试点、软删、打开「重生成」表单（`user_instruction`）→ 调 `regenerate-test-points` → 轮询 `regeneration-jobs/{job_id}`；导出按钮传 `task_id`。

---

## 7. 测试与验收

1. CI/本地：Docker Compose 启动 PostgreSQL，执行 `schema.sql`（及增量 migration 若拆分）。
2. **用例**：上传小 fixture → `start-analysis` → 断言 `test_points` 行；调用 `regenerate-test-points` → 断言旧行 `is_deleted`、新行 `replaces_id`、`regeneration_jobs.status=completed`。
3. **导出**：仅含 `is_deleted=false` 行；`include_deleted` 默认 false。

---

## 8. 自检（规格一致性）

- [x] 与「仅 PG」「重生成 A」「导出当前版」「第一版 regeneration_jobs」无矛盾。
- [x] `selected_part_ids` 与旧 `selected_section_ids` 混用风险已在 §2.2 写明处理方式。
- [x] 首跑与重跑双路径通过「共享 LLM 模块」降低重复。

---

## 9. 实现阶段建议（非本文件执行内容）

1. `schema.sql` + Alembic/单文件 migration 增加列与 `regeneration_jobs`。  
2. 实现 Repository + 合并 FastAPI 路由。  
3. 改写 `test_analysis_nodes` 全部 SQL 为 PG。  
4. 实现 `RegenerationService` 与后台执行器。  
5. 前端联调 + 集成测试。

下一步：经你审阅本文件无异议后，再编写 **implementation plan**（分 PR/分阶段任务列表），**不在本评审通过前改业务代码**。
