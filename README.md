# 智能测试点分析系统

基于 LangGraph + FastAPI 的 Word 文档智能测试点分析平台。上传需求规格文档，AI 自动按章节分析功能描述、业务规则、异常处理等模块，生成带步骤和预期结果的测试要点。

## 系统架构

```
┌─────────────────────────────────────────────────────────────┐
│                        用户浏览器                            │
│                  (index.html / Vanilla JS)                  │
└─────────────────────────┬───────────────────────────────────┘
                          │ HTTP / REST API
                          ▼
┌─────────────────────────────────────────────────────────────┐
│                    FastAPI Backend (main.py)                 │
│                                                             │
│  POST /api/upload         上传 .docx 并解析章节             │
│  POST /api/start-analysis  启动 LangGraph 分析流程          │
│  POST /api/stop-analysis   手动停止当前分析任务             │
│  GET  /api/analysis-status  轮询分析进度                    │
│  GET  /api/analysis-result  获取分析结果                    │
│  POST /api/submit-review   提交审核意见                     │
└─────────────────────────┬───────────────────────────────────┘
                          │ Python function call
                          ▼
LangGraph Workflow (test_analysis_workflow.py)

increment_iteration ──► analysis_coordinator ──► merge_aggregated
                                │                              │
                                ▼                              ▼
                         review_agent                  test_case_generation
                                │                              │
                                ▼                              ▼
                         user_review ──► finalizer ──────────► END
                                │  (needs_revision)            ▲
                                └──── reanalyze ──► coordinator┘
                                     (max_iterations limit)
                          │ LLM call
                          ▼
┌─────────────────────────────────────────────────────────────┐
│                   GLM-4.7-Flash (智谱 AI)                    │
│                                                             │
│  5 个分析 prompt（表格/功能描述/业务规则/异常处理/处理流程） │
│  1 个审核 prompt（review_agent 反思评审）                    │
└─────────────────────────────────────────────────────────────┘
```

## 项目结构

```
langchain-study/
├── backend/
│   ├── main.py                  # FastAPI 服务入口，所有 API 路由
│   └── static/
│       └── index.html           # 单页前端应用（纯 JavaScript）
├── graph/
│   └── test_analysis_workflow.py # LangGraph 工作流定义与编排
├── node/
│   ├── node_list.py             # Word 文档解析节点（已弃用，改由前端触发）
│   └── test_analysis_nodes.py   # 5 个分析节点 + merge + review + 占位生成节点
├── state/
│   └── state_list.py            # DocState：工作流全局状态定义（新增 is_cancelled 暂停支持）
├── struct_output/
│   ├── output_list.py           # 数据模型：章节、测试点、聚合测试点
│   └── test_analysis_schema.py  # LLM 输出 schema（统一为 AnalysisResult）
├── prompt/
│   └── test_analysis/           # 6 个分析 prompt 模板
├── .env                         # 环境变量（API Key、LangSmith 追踪配置）
└── README.md
```

## 核心优化记录 (死循环修复与功能增强)

### 1. 死循环风险修复
- **最大迭代限制**：在 `test_analysis_workflow.py` 中引入 `max_iterations` 状态，默认限制为 3 次迭代。若用户评审不通过且达到上限，流程将强制进入 `finalizer` 结束，防止无限消耗 Token。
- **状态写入修正**：修复了 `analysis_coordinator` 节点未将子分析节点结果写回 State 的 Bug，确保 `merge_aggregated` 节点始终能拿到完整的上下文数据。

### 2. 手动暂停功能
- **状态注入**：在 `DocState` 中新增 `is_cancelled` 标志位。
- **异步中断**：后端通过 `POST /api/stop-analysis` 接口调用 `langgraph_app.update_state` 实时将 `is_cancelled` 设为 `True`。
- **节点检查**：核心分析节点和条件跳转 `should_continue` 会优先检查取消标志，实现秒级响应停机。

### 3. Schema 重构与统一
- **模型精简**：将原本冗余的 5 个分析模型（TableAnalysisResult 等）统一为 `AnalysisResult`，降低了代码维护成本并提高了 LLM 输出的稳定性。

### 4. 流程链路优化
- **移除冗余节点**：移除了工作流中重复的 `parser` 和 `indexer` 节点，改由前端解析后通过 `parsed_data` 直接注入初始状态，显著提升首轮响应速度。
- **占位生成节点**：新增 `test_case_generation_node` 占位，为后续从测试点直接生成测试用例文档预留了扩展空间。

## 环境准备与启动

```
用户操作                    前端                       后端                        AI
──────                    ────                       ────                       ──
   │                        │                          │                          │
   │ 选择 .docx 文件         │                          │                          │
   ├────────────────────────►│                          │                          │
   │                        │ POST /api/upload          │                          │
   │                        ├─────────────────────────►│                          │
   │                        │                          │ python-docx 解析         │
   │                        │                          │ 提取章节+表格+功能分类   │
   │                        │◄─────────────────────────│                          │
   │                        │  返回 session_id + TOC    │                          │
   │◄───────────────────────┤                          │                          │
   │                        │                          │                          │
   │ 勾选章节，点击开始分析    │                          │                          │
   ├────────────────────────►│                          │                          │
   │                        │ POST /api/start-analysis  │                          │
   │                        ├─────────────────────────►│                          │
   │                        │                          │ 启动 LangGraph 线程      │
   │                        │◄─────────────────────────│                          │
   │                        │  返回 started             │                          │
   │                        │                          │                          │
   │                        │ GET /api/analysis-status  │                          │
   │                        │◄──── 每 2s 轮询 ────────►│  parser node             │
   │                        │                          │    └─ Word 解析          │
   │                        │                          │  indexer node            │
   │                        │                          │    └─ 向量化存储         │
   │                        │                          │  5 个 analyzer nodes     │
   │                        │                          │    └─ 调用 GLM API       │
   │                        │                          │  merge_aggregated        │
   │                        │                          │  review_agent            │
   │                        │                          │    └─ 调用 GLM API       │
   │                        │                          │  user_review (中断)      │
   │                        │◄──── status:             │                          │
   │                        │     awaiting_review ─────│                          │
   │                        │                          │                          │
   │  审核面板出现           │                          │                          │
   │  输入意见/批准          │                          │                          │
   ├────────────────────────►│                          │                          │
   │                        │ POST /api/submit-review   │                          │
   │                        ├─────────────────────────►│                          │
   │                        │                          │ resume workflow          │
   │                        │                          │   ├─ approved → final    │
   │                        │                          │   └─ rejected → reanalyze│
   │                        │◄───── result ───────────►│                          │
   │◄───────────────────────┤                          │                          │
   │                        │                          │                          │
   │ 卡片筛选查看测试点       │                          │                          │
   ├────────────────────────►  本地渲染，无后端请求       │                          │
```

## AI 执行逻辑

### Workflow 节点流程

```
[entry] parser ──────────────────────────────────────────────────
    │   └─ WordDocumentParser.parse_section_3()
    │      └─ 遍历 .docx body 元素（段落 + 表格）
    │      └─ 按 Heading 2/3/4 分层，提取标题、正文、表格
    │      └─ 按 Heading 4/5 自动识别功能分类
    │      └─ 返回 ParsedDocWithMetadata（54 个章节/63 个表格）
    ▼
[indexer] ──────────────────────────────────────────────────────
    │   └─ 将章节内容拼接 + 元数据 → LCDocument
    │   └─ Chroma + HuggingFaceEmbeddings → 向量库
    ▼
[analysis_coordinator] ──── 串行执行 5 个分析 ────
    │   ├── table_analyzer        ─── LLM 调用 #1
    │   ├── func_desc_analyzer    ─── LLM 调用 #2
    │   ├── business_rule_analyzer ── LLM 调用 #3
    │   ├── exception_analyzer    ─── LLM 调用 #4
    │   └── process_analyzer      ─── LLM 调用 #5
    │   每个分析节点只处理用户选中的章节
    ▼
[merge_aggregated] ─────────────────────────────────────────────
    │   └─ 将 5 个分析结果合并为单一 AggregatedTestAnalysis
    │   └─ 按 fragment index 去重，合并同片段的测试点
    ▼
[review_agent] ────────────────────────────────────────────────
    │   └─ 调用 GLM 评审：完整性评分、准确性评分、改进建议
    ▼
[user_review]  ◄── 中断，等待用户输入 ────
    │   │
    │   ├── 用户批准 (y/yes/批准/通过)
    │   │   └─ [finalizer] → END
    │   │
    │   └── 用户驳回（输入修改意见）
    │       └─ [analysis_coordinator] → 重新执行全部 5 个分析
    │          （iteration_count 递增，超 max_iterations 强制结束）
    ▼
[finalizer] ──────────────────────────────────────────────────
    └─ 将 aggregated_analysis + approval → TestAnalysisWithApproval
```

### 每个分析节点的 AI 调用

每个 `analyzer` 节点执行流程完全相同：

```
1. _get_selected_sections(state)
   └─ 读取 state["selected_section_indices"]
   └─ 根据用户勾选的章节索引，从 parsed_data.sections 中过滤
   └─ 如果列表为空，分析所有章节

2. 按类型提取数据
   └─ table_analyzer:      遍历 sec.tables → 格式化为表格文本
   └─ func_desc_analyzer:  遍历 sec.function_sections，过滤 type="func_desc"
   └─ business_rule_analyzer: 过滤 type in ("business_rule", "操作权限")
   └─ exception_analyzer:  过滤 type="exception"
   └─ process_analyzer:    过滤 type in ("process", "处理流程")

3. _invoke_structured(llm, prompt_text, output_cls)
   └─ 调用 GLM-4.7-Flash API
   └─ 清理响应中的 ```markdown 包装
   └─ json.loads → pydantic model_validate

4. _build_aggregated_analysis(result, source_type, ...)
   └─ 将 LLM 返回的 SourceFragment + TestPointItem
   └─ 转为 AggregatedTestAnalysis（含 steps / expected_results）
```

### 数据流

```
用户上传 .docx
    │
    ▼
sections_content（API 返回给前端，用于展示）
    │
    ▼
parsed_data（传入 workflow 的 DocState）
    │
    ├── 前端只展示：功能分类卡片 + 表格
    ├── workflow 使用：sections[].tables → table_analyzer
    │                    sections[].function_sections → 各 analyzer
    │
    ▼
5 个 AggregatedTestAnalysis（每个类型一个）
    │
    ▼ merge（按 fragment index 去重合并）
    │
    ▼
单个 AggregatedTestAnalysis → review_agent 评审
    │
    ▼
最终输出：fragments[].test_points[]（含 steps / expected_results）
    │
    ▼
前端展示：按章节 → 按类型筛选 → 测试点列表（含步骤/预期结果）
```

## 快速启动

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 配置环境变量
cp .env.example .env
# 编辑 .env 填入 API Key

# 3. 启动服务
python3 backend/main.py

# 4. 打开浏览器访问
open http://localhost:8000
```

---

## 修改记录：LangGraph State 传输一致性问题修复 (2026-04-28)

### 背景

LangGraph TypedDict state 中各节点返回的数据类型不一致——有的存 Pydantic 对象，有的存 dict，导致节点间取值时混用 `.属性` 和 `.get("key")` 两种访问方式，数据流脆弱不可靠。此外，迭代循环中旧状态残留导致下游节点读到过期数据。

### 修改 #1 — 统一 State 存储格式为 dict

**文件**: `node/test_analysis_nodes.py`  
**位置**: `analysis_coordinator_node` 函数

- **问题**: 子分析节点（`table_analysis_node` 等）返回 Pydantic `AggregatedTestAnalysis` 对象，`analysis_coordinator_node` 直接将这些对象存入 state，但 `aggregated_analysis` 又被 `model_dump()` 转成了 dict。同一个 state 中 dict 和对象混存。
- **修复**: 
  - 拆分为 `analyses_objects`（保留 Pydantic 对象供 `_merge_aggregated_analyses` 使用）和 `individual_results`（dict，供 state 存储）
  - 所有子分析结果通过 `val.model_dump()` 统一转为 dict 再写入 state

```python
# 修改前
individual_results[state_key] = val          # Pydantic 对象直接入 state
analyses.append(val)                          # analyses 列表混用

# 修改后
individual_results[state_key] = val.model_dump() if (...) else None  # 统一为 dict
analyses_objects.append(val)                  # 仅对象列表用于合并
```

---

### 修改 #2 — 迭代循环清零旧状态

**文件**: `node/test_analysis_nodes.py`  
**位置**: `analysis_coordinator_node` 函数返回语句

- **问题**: 当流程因用户驳回进入 `needs_revision` 重分析时，旧的 `approval_feedback`、`user_review`、`is_approved` 仍残留在 state 中，直到被 `review_agent`/`user_review` 覆盖。中间窗口期数据不一致。
- **修复**: 每次 `analysis_coordinator_node` 返回时，显式清零三个字段：

```python
# 修改后（有数据分支 + 无数据分支均清零）
return {
    "aggregated_analysis": merged.model_dump(),
    "approval_feedback": None,      # 新增：清零旧审核
    "user_review": None,            # 新增：清零旧用户审核
    "is_approved": False,           # 新增：重置为未批准
    **individual_results,
}
```

---

### 修改 #3 — `create_final_result` 类型修复

**文件**: `graph/test_analysis_workflow.py`  
**位置**: `create_final_result` 函数

- **问题**: `approval` 来自 state 为 dict 格式，但 `TestAnalysisWithApproval(approval=...)` 期望 `ApprovalFeedback` Pydantic 对象
- **修复**: 增加 dict → Pydantic 对象转换：

```python
# 修改前
final_result = TestAnalysisWithApproval(
    analysis=merged_analysis,
    approval=approval,                    # 直接传 dict，类型不匹配
    ...
)

# 修改后
approval_obj = ApprovalFeedback.model_validate(approval) if isinstance(approval, dict) else approval
final_result = TestAnalysisWithApproval(
    analysis=merged_analysis,
    approval=approval_obj,                # 传 Pydantic 对象
    ...
)
```

- 同时将 `is_final` 的判断从 `(user_review and user_review.approved)` 改为 `getattr(user_review, "approved", False)`，防御性兼容 dict/Pydantic 对象。

---

### 修改 #4 — `merge_aggregated_analysis_node` 一致性修复

**文件**: `node/test_analysis_nodes.py`  
**位置**: `merge_aggregated_analysis_node` 函数

- **问题**: 该节点从 state 取出的 `table_aggregated` 等字段现在是 dict，但 `_merge_aggregated_analyses` 需要 Pydantic 对象
- **修复**: 在合并前将 dict 转回 Pydantic 对象，返回时再转为 dict：

```python
# 修改前
merged = _merge_aggregated_analyses(valid)     # valid 里是 dict，merge 会失败
return {"aggregated_analysis": merged}          # 返回 Pydantic 对象

# 修改后
valid_objects = [AggregatedTestAnalysis.model_validate(a) if isinstance(a, dict) else a for a in valid]
merged = _merge_aggregated_analyses(valid_objects)
return {"aggregated_analysis": merged.model_dump()}
```

---

### 修改 #5 — `should_continue` 防御性属性访问

**文件**: `graph/test_analysis_workflow.py`  
**位置**: `should_continue` 函数

- **问题**: `user_review.approved` 直接属性访问，若 state 中存储的是 dict 则会报 `AttributeError`
- **修复**: 改用 `getattr(user_review, "approved", False)` 兼容 dict 和 Pydantic 对象

---

### 数据流一致性总览

```
analysis_coordinator → state: 全部 dict / None ✅
      ↓
review_agent        → state: approval_feedback(dict), is_approved(bool) ✅
      ↓
user_review         → state: user_review(UserReviewStatus), is_approved(bool) ✅
      ↓
should_continue     → 读取: getattr(user_review, "approved", False) ✅
      ↓
finalizer           → dict → Pydantic 对象 → TestAnalysisWithApproval ✅
```

---

## 数据库设计方案 (v3.0)

> **目标**：将文档解析结果、测试用例、格式审查、覆盖度审查全部持久化到数据库，替代原有的 LangGraph State 全量上下文传递，减小 Token 消耗并支持增量分析。

### 设计原则

| 原则 | 说明 |
|------|------|
| **State 瘦身** | Workflow state 只保留当前任务必要的轻量引用（task_id、document_id），不再携带全量数据 |
| **DDD 分层存储** | 文档解析库、用例库、审查结果库各自独立，通过外键关联 |
| **JSONB 存可变结构** | `steps`、`expected_results` 等可变数组用 JSONB，固定字段用列 |
| **UUID 主键** | 所有主键由应用层生成（`uuid.uuid4()`），避免自增 ID 在分布式环境下的冲突 |
| **软关联** | 测试点通过 `source_fragment_id` 关联原文片段，支持原文更新后测试点跟随 |
| **独立数据库选型** | 使用 PostgreSQL 15+，利用 JSONB 索引和全文搜索能力 |

### 新 Workflow 流程

```
[上传文档]
    │
    ▼
[解析文档] ──► 写入 documents / document_sections / section_tables / section_function_parts
    │              (SQL 第 1 部分)
    ▼
[用户选中章节] ──► 创建 analysis_tasks 记录，传入 selected_section_ids
    │              (SQL 第 2 部分)
    ▼
[analysis_coordinator] ◄── 从 DB 读取选中章节（仅取该任务需要的行）
    │   ├─ 5 个子分析节点分别调用 LLM
    │   └─ 输出写入 aggregated_analyses / source_fragments / test_points
    │              (SQL 第 3 部分)
    ▼
[格式审查 Agent] ──► 逐行检查 test_points
    │   ├─ steps 与 expected_results 数量是否一致
    │   ├─ test_type / priority 是否缺失 → 自动补充
    │   └─ 更新 test_points.format_valid / format_issues / auto_filled_fields
    │   └─ 汇总写入 format_review_results
    │              (SQL 第 4 部分)
    ▼
[覆盖度审查 Agent] ──► 读取整个 document_sections + test_points
    │   ├─ 对比：哪些章节无测试点覆盖？
    │   ├─ 哪些功能分类 (func_desc/business_rule/exception/process) 覆盖不足？
    │   ├─ 输出覆盖率评分 + 遗漏区域 + 建议补充的测试点
    │   ├─ 写入 coverage_review_results
    │   └─ 缺口详情写入 coverage_gaps
    │              (SQL 第 5、6 部分)
    ▼
[完成] ✅
```

### 表结构总览

```
┌─────────────────────────────────────────────────────────────────────┐
│                      第 1 部分 · 文档解析库                           │
│                                                                      │
│  documents (文档)                                                     │
│  ├── id, file_name, file_path, file_size, status,                   │
│  │   total_sections, total_tables                                    │
│  │                                                                   │
│  └──► document_sections (章节)                                       │
│        ├── id, document_id, section_index, title, level, content     │
│        │   meta_level_1~4                                            │
│        │                                                             │
│        ├──► section_tables (表格)                                    │
│        │     id, section_id, table_index, headers(JSONB), rows(JSONB)│
│        │                                                             │
│        └──► section_function_parts (功能分类)                         │
│              id, section_id, part_index, section_type, content       │
│              tables_json(JSONB)                                      │
├─────────────────────────────────────────────────────────────────────┤
│                      第 2 部分 · 分析任务                             │
│                                                                      │
│  analysis_tasks                                                      │
│  ├── id, document_id, status, selected_section_ids(JSONB)            │
│  │   iteration_count, max_iterations                                 │
│  │   error_message, created_at, completed_at                         │
├─────────────────────────────────────────────────────────────────────┤
│                      第 3 部分 · 测试用例库                           │
│                                                                      │
│  aggregated_analyses (按 source_type 拆分)                            │
│  ├── id, task_id, source_type, total_test_points,                    │
│  │   total_fragments, coverage_analysis                              │
│  │                                                                   │
│  ├──► source_fragments (原文片段)                                    │
│  │     id, aggregated_analysis_id, fragment_index,                   │
│  │     section_title, content                                        │
│  │                                                                   │
│  └──► test_points (核心用例表)                                       │
│        id, task_id, source_fragment_id, test_point_id,               │
│        description, source_section, source_type, source_content,     │
│        priority, test_type,                                          │
│        steps(JSONB), expected_results(JSONB),                        │
│        format_valid, format_issues(JSONB), auto_filled_fields(JSONB) │
├─────────────────────────────────────────────────────────────────────┤
│                      第 4 部分 · 格式审查                             │
│                                                                      │
│  format_review_results                                               │
│  ├── id, task_id, total_test_points, format_valid_count,             │
│  │   format_invalid_count, auto_fixed_count,                         │
│  │   issues_summary(JSONB), auto_fill_log(JSONB)                     │
├─────────────────────────────────────────────────────────────────────┤
│                      第 5、6 部分 · 覆盖度审查                        │
│                                                                      │
│  coverage_review_results                                             │
│  ├── id, task_id, completeness_score, accuracy_score,                │
│  │   issues(JSONB), suggestions(JSONB), missing_test_points(JSONB),  │
│  │   missing_areas(JSONB), coverage_analysis                         │
│  │                                                                   │
│  └──► coverage_gaps (缺口详情)                                       │
│        id, review_id, task_id, gap_type, section_id,                 │
│        description, suggested_test_points(JSONB)                     │
└─────────────────────────────────────────────────────────────────────┘
```

### 关键字段映射（原 DocState → SQL）

| 原 State 字段 | SQL 表.列 | 说明 |
|---------------|-----------|------|
| `parsed_data` | `documents` + `document_sections` + `section_tables` + `section_function_parts` | 拆分为 4 张表 |
| `selected_section_indices` | `analysis_tasks.selected_section_ids` | 存章节 UUID 列表 |
| `table_aggregated` | `aggregated_analyses` WHERE `source_type='table'` | 按 type 分存 |
| `func_desc_aggregated` | `aggregated_analyses` WHERE `source_type='func_desc'` | 同上 |
| `aggregated_analysis` | `test_points` (扁平化) | 不再存嵌套对象，直接存测试点行 |
| `approval_feedback` | `coverage_review_results` | 审核改为覆盖度审查 |
| `iteration_count` | `analysis_tasks.iteration_count` | |

### 格式审查 Agent 逻辑

```python
# 伪代码
def format_review_node(task_id: str):
    test_points = db.query("SELECT * FROM test_points WHERE task_id = ?", task_id)

    for tp in test_points:
        issues = []
        # 规则 1: steps 与 expected_results 数量一致
        if len(tp.steps) != len(tp.expected_results):
            issues.append({
                "field": "steps/expected_results",
                "issue": f"steps 有 {len(tp.steps)} 项, expected_results 有 {len(tp.expected_results)} 项, 数量不匹配"
            })

        # 规则 2: 缺失字段自动补充
        auto_filled = {}
        if not tp.priority or tp.priority not in ("高", "中", "低"):
            auto_filled["priority"] = _infer_priority(tp.description)
        if not tp.test_type:
            auto_filled["test_type"] = _infer_test_type(tp.source_type, tp.description)

        # 规则 3: test_point_id 格式校验 (TP-{SOURCE}-{NNN})
        if not re.match(r"^TP-\w+-\d+$", tp.test_point_id):
            issues.append({"field": "test_point_id", "issue": "ID 格式不符合规范"})

        db.update("test_points", {
            "format_valid": len(issues) == 0,
            "format_issues": json.dumps(issues),
            "auto_filled_fields": json.dumps(auto_filled),
            **auto_filled
        }, where={"id": tp.id})
```

### 覆盖度审查 Agent 逻辑

```python
# 伪代码
def coverage_review_node(task_id: str):
    # 1. 读取文档所有章节（仅取 ID + 标题 + 功能分类类型）
    task = db.query("SELECT document_id FROM analysis_tasks WHERE id = ?", task_id)
    all_sections = db.query("""
        SELECT ds.id, ds.title, ds.meta_level_2, ds.meta_level_3,
               sfp.section_type
        FROM document_sections ds
        LEFT JOIN section_function_parts sfp ON sfp.section_id = ds.id
        WHERE ds.document_id = ?
    """, task.document_id)

    # 2. 读取所有已生成测试点
    test_points = db.query("""
        SELECT tp.test_point_id, tp.source_section, tp.source_type,
               tp.priority, tp.description
        FROM test_points tp
        WHERE tp.task_id = ?
    """, task_id)

    # 3. 构造覆盖度审查 prompt
    prompt = COVERAGE_REVIEW_PROMPT.format(
        all_sections=json.dumps(all_sections),
        test_points=json.dumps(test_points),
        total_sections=len(all_sections),
        total_test_points=len(test_points),
    )

    # 4. LLM 审查
    result = llm.invoke(prompt)  # 输出 CoverageReviewResult

    # 5. 写入结果
    db.insert("coverage_review_results", {
        "task_id": task_id,
        "completeness_score": result.completeness_score,
        "accuracy_score": result.accuracy_score,
        "issues": json.dumps(result.issues),
        "suggestions": json.dumps(result.suggestions),
        "missing_test_points": json.dumps(result.missing_test_points),
        "missing_areas": json.dumps(result.missing_areas),
        "coverage_analysis": result.coverage_analysis,
    })

    # 6. 写入缺口详情
    for gap in result.gaps:
        db.insert("coverage_gaps", {
            "review_id": review_id,
            "task_id": task_id,
            "gap_type": gap.gap_type,
            "section_id": gap.section_id,
            "description": gap.description,
            "suggested_test_points": json.dumps(gap.suggested_test_points),
        })
```

### SQL 文件位置

完整 DDL 脚本位于 [`sql/schema.sql`](file:///Users/yyf/langchain-study/sql/schema.sql)，包含：
- 10 张业务表 + 1 个触发器函数
- 4 个索引（按文档查询、按任务查询、按类型查询、按格式状态查询）
- 3 个便捷视图（文档概览、任务测试点汇总、覆盖度审查全貌）

### New State (瘦身后)

```python
class DocStateV3(TypedDict):
    task_id: str                       # analysis_tasks.id
    document_id: str                   # documents.id
    selected_section_ids: List[str]    # 用户选的章节 UUID 列表
    iteration_count: int
    max_iterations: int
    status: str                        # running → format_reviewing → coverage_reviewing → completed
    error_message: Optional[str]
    is_cancelled: bool
```

---

## 环境变量

| 变量名 | 说明 | 示例 |
|--------|------|------|
| `GLM_API_KEY` | 智谱 AI API Key | `xxx.CqRJwzvxkMCi1RWX` |
| `GLM_BASE_URL` | 智谱 API 地址 | `https://open.bigmodel.cn/api/coding/paas/v4` |
| `GLM_MODEL` | 模型名称 | `GLM-4.7-Flash` |
| `DATABASE_URL` | PostgreSQL 连接串 | `postgresql://user:pass@localhost:5432/test_analysis` |
| `LANGSMITH_TRACING` | LangSmith 追踪开关 | `true` |
| `LANGSMITH_API_KEY` | LangSmith API Key | `lsv2_pt_xxx` |
| `LANGSMITH_PROJECT` | LangSmith 项目名 | `langchaintest` |

## 版本优化

### v1.0 → v2.0 关键优化记录（面试亮点）

以下是该项目从原型到生产可用过程中解决的关键技术问题，可作为 Agent 工程师面试中的重要项目经验。

---

#### Batch 1：LangGraph Workflow 死循环修复

**问题现象**：5 个分析节点（table/func_desc/business_rule/exception/process）通过 `add_edge` 并行 fan-in 到 `merge_aggregated`。LangGraph 的 fan-in 机制导致该节点执行 **5 次**——每个上游节点完成触发一次。前 4 次触发走 `merge_wait → END` 分支，**提前终止了整个 Workflow**，第 5 个分析器来不及执行就结束了。

**根因分析**：
1. LangGraph 的 `add_edge` 是"每收到一次输入就执行一次"，不同于传统 DAG 的"等待所有上游完成"
2. 任何子路径到达 `END` 后，整个 Workflow 执行即终止，剩余分支废弃
3. 尝试过计数器（`analysis_completed_count`）和 flag 列表（`analysis_run_flags`）方案，但 fan-in 下 state 修改不跨分支累积，方案都不可靠

**解决方案**：**去掉 5 个并行 LangGraph Node，合并为 1 个串行 `analysis_coordinator_node`**
```python
def analysis_coordinator_node(state: DocState) -> Dict:
    result = {}
    for node_fn, state_key in [
        (table_analysis_node, "table_aggregated"),
        (func_desc_analysis_node, "func_desc_aggregated"),
        (business_rule_analysis_node, "business_rule_aggregated"),
        (exception_analysis_node, "exception_aggregated"),
        (process_analysis_node, "process_aggregated"),
    ]:
        ret = node_fn(state)
        if state_key in ret:
            result[state_key] = ret[state_key]
    return result
```
- 5 个 LLM 调用在一个 Node 内 **串行执行**，瓶颈在 LLM API 延迟而非 CPU，所以不影响整体速度
- `parser → indexer → analysis_coordinator → merge_aggregated → review_agent → user_review`
- `needs_revision` 分支直接回 `analysis_coordinator`，无需任何计数器或 flag，天然正确
- 删除了 `merge_wait` 节点、`reanalyze` 节点、`analysis_run_flags` 状态、5 条 fan-in 边

**面试要点**：LangGraph fan-in 下的状态隔离陷阱——`operator.add` reducer 在并行分支中不跨分支生效；串行 vs 并行的本质权衡——LLM 调用是 IO 密集型而非 CPU 密集型，串行不损失性能且大幅简化架构；什么时候该用并行的设计决策依据。

---

#### Batch 2：行列式表格解析与合并单元格处理

**问题现象**：Word 文档中表格的前 1-2 行是合并单元格（如"功能名称：输入节点-添加"跨越全部 17 列），直接提取导致表头全部为相同内容，破坏后续 AI 分析。

**根因分析**：原始 `_extract_table()` 固定取第一行作为表头，未考虑 Word 合并单元格（`w:merge`）导致的重复内容。

**解决方案**：
```python
# 自动跳过合并行：检测到一行所有列内容相同（len(set(row)) == 1）则跳过
header_start = 0
while header_start < len(rows):
    if len(set(rows[header_start])) == 1 and len(rows[header_start]) > 1:
        header_start += 1  # 跳过合并行
    else:
        break  # 找到真正的表头
headers = rows[header_start]
data_rows = rows[header_start + 1:]
```
- 无需依赖 `w:merge`/`w:gridSpan` 等底层 XML 解析
- 逻辑通用：任何"所有列内容一致"的行都被判定为合并行并跳过
- 支持多个连续合并行的场景

**面试要点**：从业务现象反推技术方案；不依赖底层 XML 的通用合并单元格检测算法。

---

#### Batch 3：API 调用链优化——从 OpenAI 到 GLM 的适配

**问题 1——模型兼容性**：需要从 OpenAI 切换到 GLM-4.7-Flash，两者 API 格式高度兼容但存在差异。
- 使用 `ChatOpenAI` 类指定 `api_key` 和 `base_url` 接入 GLM 网关
- 模型配置下沉到 `.env`，零代码切换模型

**问题 2——Embedding 配额不足**：`OpenAIEmbeddings()` 的 API Key 无 Embedding 额度，返回 429。
- 替换为 `HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")`
- 本地 CPU 推理，零 API 成本，无需网络依赖

**问题 3——结构化输出兼容性**：GLM 的 `response_format`/`with_structured_output` 支持不完整，频繁返回 markdown 包裹的 JSON 导致 pydantic 解析失败。
```python
# 自定义 _invoke_structured 替代 with_structured_output
def _invoke_structured(llm, prompt_text, output_cls):
    raw = llm.invoke(prompt_text)
    content = raw.content.strip()
    content = re.sub(r'^```(?:markdown|json|)\s*', '', content)  # 删前导包装
    content = re.sub(r'\s*```$', '', content)                    # 删尾部包装
    data = json.loads(content)                                    # 手动 JSON 解析
    return output_cls.model_validate(data)                        # pydantic 校验
```
- 所有 6 个分析节点（含 review_agent）统一使用此方法
- Prompt 模板同步添加"直接输出纯 JSON，不要使用 markdown 代码块"指令

**面试要点**：LLM 适配层的设计——如何构建模型无关的调用抽象；非标准输出的容错处理；Prompt Engineering 与代码逻辑的双层保障。

---

#### Batch 4：前端交互体验优化

**1. 中间内容区重构**：去掉原始段落文本展示，改为**功能分层卡片**展示（功能描述-蓝色、业务规则-红色、异常处理-橙色、处理流程-青色、操作权限-紫色），每张卡片可点击筛选对应测试点。

**2. 左侧目录层级化**：按 `level_2`（模块名）分组，`level_3` 为主标题，`level_4` 为副标题缩进显示，仅展示关键类型标签，左侧增加活跃指示条。

**3. 测试点展示优化**：每项测试点附带**步骤（steps）**和**预期结果（expected_results）**，步骤格式为 `1. 操作入口动作 / 2. 测试动作 / 3. 测试观测动作`，预期结果与步骤一一对应。

**4. section_title 模糊匹配**：LLM 输出与实际章节标题存在差异时，通过双向前缀匹配容错，确保测试点正确渲染。

**5. 分析完成自动展示**：`fetchResult` 增加兜底逻辑，无活跃节点时自动选中第一个章节并展示测试点。

**面试要点**：AI 输出不确定性在前端的容错处理；状态驱动的 UI 渲染时序。

---

#### Batch 5：按需分析与流式工作流

**问题**：分析时一次性处理全部 54 个章节，耗时高且数据冗余；表格作为所有分析节点的输入，而非仅表格分析节点使用。

**解决方案**：
- `DocState.selected_section_indices`：前端勾选章节索引传入 Workflow
- `_get_selected_sections()`：统一过滤，所有分析节点共用
- 每个分析节点**独立抽取**对应类型的数据：table_analyzer 只读 `sec.tables`，func_desc_analyzer 只读 `sec.function_sections`（type="func_desc"），以此类推
- 数据不再从 LLM 响应中提取 table 信息，而是从已解析的结构化数据中获取

**面试要点**：如何避免将"AI 能做什么"与"AI 应该做什么"混淆——结构化数据在前、AI 分析在后的架构设计。

---

#### Batch 6：代码资产清理与安全加固

| 优化项 | 操作 |
|--------|------|
| API Key 泄露清理 | 从代码中移除所有硬编码密钥，统一使用 `.env` + `os.environ[]` |
| 删除未使用代码 | 移除 13 个废弃文件、3 个未使用的 TypedDict、2 个无用函数 |
| 向量库存清理 | 每次重启自动删除旧 chroma_db，避免索引污染 |
| 上传缓存清理 | 移除 uploads/ 中 29 个临时文件 |
| 合并单元格探测 | 纯逻辑检测，无需依赖 XML 命名空间 |

---

#### 架构设计思想总结

```
┌──────────────────────────────────────────────────────────┐
│               Agent Workflow 设计原则                     │
├──────────────────────────────────────────────────────────┤
│  1. 状态驱动：DocState 是唯一的真理源（Single Source     │
│     of Truth），所有节点通过读写 state 通信               │
│                                                          │
│  2. 串行优于并行：LLM 调用是 IO 密集型，串行执行不损失   │
│     性能，且彻底避免 fan-in 同步问题                      │
│                                                          │
│  3. 可重入性：needs_revision → analysis_coordinator      │
│     分支确保迭代途中状态不丢失，天然正确                   │
│                                                          │
│  4. 隔离分析：选中章节索引 + 类型过滤，每个 analyzer      │
│     只处理自己关注的数据子集                              │
│                                                          │
│  5. 容错分层：前端模糊匹配 → 后端自定义解析 → prompt     │
│     指令约束，三层保障应对 LLM 输出的不确定性               │
│                                                          │
│  6. 模型无关：通过 ChatOpenAI + 自定义 base_url 对接      │
│     不同模型，切换只需改 .env                             │
└──────────────────────────────────────────────────────────┘
```
