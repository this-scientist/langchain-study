# 智能测试点 / 用例生成系统

基于 **FastAPI** 提供 Web 与 API，**LangGraph** 编排分析 Agent，**SQL 数据库** 持久化文档结构与生成结果。用户上传 Word 需求说明（`.docx`），系统解析为章节与原子片段，选中片段后触发大模型分析，将测试点写入数据库供查询与导出。

---

## 一、项目整体结构

| 路径 | 职责 |
|------|------|
| `backend/main.py` | FastAPI 应用：上传、文档查询、任务创建/启动、进度与结果 API、静态前端挂载 |
| `run_server.py` | 根目录一键启动：读取 `.env` 中 `UVICORN_*` 并运行 uvicorn |
| `.env.example` | 环境变量模板（复制为 `.env`） |
| `backend/static/frontend/` | 实际由服务挂载的前端静态资源（`/` 指向 `index.html`） |
| `frontend/` | 与上表内容重复的源码目录，需与 `static/frontend` 保持同步，否则易出现「改了一处另一处未更新」 |
| `graph/test_analysis_workflow.py` | LangGraph 图定义与 `run_task_analysis` 入口 |
| `node/node_list.py` | `WordDocumentParser`：按「功能分析」等标题结构解析 `.docx` |
| `node/test_analysis_nodes.py` | LangGraph 节点：`prepare_data`、`single_analysis`、`rule_analysis` |
| `state/state_list.py` | `DocState`（TypedDict）：运行期轻量状态，以 ID 为主 |
| `db/__init__.py` | 根据 `DB_MODE` 选择 `LocalDatabaseManager`（SQLite）或 `DatabaseManager`（PostgreSQL） |
| `db/local_database.py` / `db/database.py` | 两套数据访问实现 |
| `prompt/test_analysis/` | 表格、权限、规则等场景的 Prompt 模板 |
| `struct_output/test_analysis_schema.py` | LLM 结构化输出（如 `SinglePartAnalysisResult`） |
| `sql/schema.sql` | **PostgreSQL** 建表脚本（视图、字段与本地 SQLite 自建表并非一一对应时需分别维护） |
| `uploads/` | 上传文件存储目录 |

---

## 二、端到端执行逻辑（框架主路径）

### 1. Web 与数据准备

1. 用户访问根路径 `/`，返回 `backend/static/frontend/index.html`（若存在）。
2. **上传** `POST /api/upload`：保存文件到 `uploads/`，`WordDocumentParser.parse_section_3()` 解析文档，通过 `db_manager.save_parsed_document(...)` 写入文档、章节、表格、功能片段表；返回 `doc_id` 与目录树 `toc`（含各 `section_function_parts` 的 `id`）。
3. **预览** `GET /api/document-preview/{doc_id}`：供前端展示章节与片段正文。
4. **创建任务占位** `POST /api/create-task?doc_id=`：在库中插入一条 `analysis_tasks`（与后续「启动分析」逻辑并存时需留意是否重复建任务）。
5. **启动分析** `POST /api/start-analysis`：请求体为 `task_id`（可选）与 `selected_part_ids`（必选）。服务端根据第一个 `part_id` 反查 `doc_id` 与 `file_path`，**再次**向 `analysis_tasks` 插入记录（`task_id` 可为客户端指定），然后启动**守护线程**调用 `run_task_analysis(...)`。

### 2. 运行中状态：内存 + 数据库

- `backend/main.py` 中的全局字典 `sessions[task_id]` 保存**当前进程内**正在执行任务的简要进度（`status`、`progress`、`message` 等）。
- 任务最终状态、错误信息以 `db_manager.update_task_status` 等形式写入数据库。
- 刷新页面或服务多进程部署时，**仅依赖内存的进度会丢失**，需以数据库中的 `analysis_tasks` 为准或改进进度回写。

### 3. LangGraph 工作流（与 README 旧版描述的差异）

当前图**不是**「单线程循环 fetch → analysis → review → 回到 fetch」的闭环，而是：

1. **入口节点** `prepare_data`（`prepare_data_node`）  
   - 读入 `DocState` 中的 `selected_part_ids`。  
   - 通过 `db_manager.get_function_part` 等**多次查询 SQL**，将片段分为：表格关联 ID、操作权限 ID、规则类拼接正文等；写回 `table_part_ids`、`permission_part_ids`、`rule_combined_content`、`_table_section_groups` 等。

2. **条件边** `fan_out_to_analyses`  
   - 使用 LangGraph 的 `Send`，向 `rule_analysis` 与多个 `single_analysis` **并发派发**子图调用（每个 Send 携带各自子 state 字段）。  
   - `single_analysis` 与 `rule_analysis` 执行完后均直接 **`END`**，图中**没有**汇聚节点做统一 reduce/merge。

3. **子节点**  
   - `single_analysis_node`：按表格组或权限片段组拼 Prompt，调用 GLM（`ChatOpenAI` 配置为智谱等兼容接口），解析为结构化结果后 **`db_manager.save_test_point`** 落库。  
   - `rule_analysis_node`：对合并后的规则正文一次性分析，同样落库。

4. **检查点**  
   - 使用 `MemorySaver()` 编译图；**进程重启后 LangGraph checkpoint 不持久**，与「测试结果在 SQL」互补：业务结果以表为准，图状态仅辅助同线程内调试。

5. **入口函数** `run_task_analysis`：`app.invoke(initial_state, config)`，`thread_id` 与 `task_id` 对齐，便于与检查点配置关联。

### 4. `DocState` 与 SQL 的分工

- **`DocState`**（`state/state_list.py`）：承载 `task_id`、`doc_id`、`file_path`、选中片段 ID 列表、预处理得到的分类 ID/规则文本、取消标记等；**不**存放完整文档正文，正文与片段内容以 **SQL 查询在节点内按需加载**。
- **数据库**：权威存储文档层级、`section_function_parts`、`section_tables`、`analysis_tasks`、`test_points` 等；前端结果列表来自 `GET /api/task-results/{task_id}`，内部由 `db_manager.get_analysis_results` 聚合（PostgreSQL 侧常配合视图如 `v_task_test_points`）。

---

## 三、数据库切换与已知割裂（`state`/SQL 层问题集中区）

- 环境变量 **`DB_MODE`**（见 `db/__init__.py`）：  
  - `local`（默认）：`LocalDatabaseManager`，SQLite 文件 `local_data.db`，表结构在 `local_database._init_db` 中初始化。  
  - 其他值：`DatabaseManager`，**PostgreSQL**，连接信息来自环境变量（如 `DB_HOST`、`DB_NAME` 等）。

- **节点内 SQL 大量使用 SQLite 占位符 `?` 与 `conn.execute`**（`node/test_analysis_nodes.py`、`prepare_data_node`、`single_analysis_node`、`rule_analysis_node`）。在 **`DB_MODE=local`** 下与 `LocalDatabaseManager._get_conn()` 一致。若切换到 PostgreSQL，需改为 `psycopg2` 的 `%s` 与 `cursor.execute` 等，否则**无法直接运行**。

- **`save_test_point` 签名不一致**：本地实现包含 `transaction_name`、`test_case_path` 等扩展参数；`db/database.py` 中 PostgreSQL 版本为另一套字段集合。节点当前按**本地**签名调用，远程库未对齐前会出错。

- **`start-analysis` 建表**：`main.py` 内对 `analysis_tasks` 使用 `INSERT ... ?`，与 SQLite 一致；PostgreSQL 建表脚本在 `sql/schema.sql`，类型为 UUID/TIMESTAMPTZ 等，与本地 TEXT 简化表**不完全等价**，迁移与联调需单独梳理。

---

## 四、前端说明与常见问题

- 浏览器实际加载的是 **`/static/...`** 下文件还是根路径返回的 `index.html`，取决于 `backend/static/frontend` 是否已拷贝最新 `frontend/`。两处不同步会导致接口路径、页面逻辑表现不一致。
- 前端 `api.js` 中部分请求使用相对路径 `/api/...`；若前后端不同源需配置反向代理或 CORS（后端已 `allow_origins=["*"]`）。
- 轮询 `GET /api/task-status/{task_id}`：运行中优先读 `sessions`，结束后读库；**细粒度进度**若未从节点写回 `sessions` 或库，界面可能长期停留在笼统文案。

---

## 五、环境变量与启动

### 5.1 `.env` 里写什么（不要把 shell 命令写进 `.env`）

`.env` 只支持 **`KEY=value`** 形式的环境变量。`GLM_*`、`DB_MODE`、`DB_*` 等放在 `.env` 后，**不必**在终端里再写一长串 `export`。项目已在 `backend/main.py`、`db/__init__.py` 中 `load_dotenv`。

可选的 HTTP 相关变量（用于简化启动，见下）：

- `UVICORN_HOST`：默认 `0.0.0.0`  
- `UVICORN_PORT`：默认 `8000`  
- `UVICORN_RELOAD`：默认 `true`（开发热重载）

可参考仓库根目录 **`.env.example`** 复制为 `.env` 再填写。

**其他常见变量**（具体以代码为准）：

- `DB_MODE`：`local`（SQLite）或非 `local`（PostgreSQL）。  
- PostgreSQL：`DB_HOST`、`DB_PORT`、`DB_NAME`、`DB_USER`、`DB_PASSWORD`。  
- 大模型：`GLM_API_KEY`、`GLM_BASE_URL`、`GLM_MODEL`（`node/test_analysis_nodes.py`）。

### 5.2 推荐：一条命令启动（根目录）

```bash
python run_server.py
```

等价于根据 `.env` 中的 `UVICORN_*` 调用 uvicorn；无需在命令行重复 host/port/reload。

### 5.3 等价：仍可直接用 uvicorn

```bash
uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
```

（`.env` 仍会被应用代码加载。）

### 5.4 PostgreSQL 初始化（仅在使用远程库时）

```bash
psql -h <host> -U <user> -d <dbname> -f sql/schema.sql
```

> 说明：仓库内可能未包含 `requirements.txt`；请根据 import 安装 `fastapi`、`uvicorn`、`langgraph`、`langchain-openai`、`python-docx`、`psycopg2-binary`、`openpyxl`、`python-dotenv` 等依赖。

---

## 六、小结

| 层次 | 作用 |
|------|------|
| FastAPI | HTTP API、静态页、后台线程触发分析 |
| LangGraph | `prepare_data` → 多路 `Send` → 并行分析节点 → `END`；状态以 ID + 预处理字段为主 |
| SQL | 文档与片段的权威存储、测试点持久化、任务列表与导出 |
| 前端 | 上传、选片段、启任务、轮询状态、展示/导出结果；与静态目录双份维护时需警惕漂移 |

当前架构 strengths：**片段化需求、按类型分流、结果先入 SQL**。主要技术债：**双数据库抽象未在节点层统一**、**前端双路径**、**任务创建与 `start-analysis` 插入逻辑可能重复**、**停止分析**在图中未全面消费 `is_cancelled`。后续迭代可优先统一 DB 访问层与单一前端发布目录。
