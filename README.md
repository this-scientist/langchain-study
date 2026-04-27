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
│  GET  /api/analysis-status  轮询分析进度                    │
│  GET  /api/analysis-result  获取分析结果                    │
│  POST /api/submit-review   提交审核意见                     │
└─────────────────────────┬───────────────────────────────────┘
                          │ Python function call
                          ▼
┌─────────────────────────────────────────────────────────────┐
│                    LangGraph Workflow                        │
│              (test_analysis_workflow.py)                     │
│                                                             │
│  parser ──► indexer ──► [5 x analyzer nodes]               │
│                              │                              │
│                              ▼                              │
│                    merge_aggregated                          │
│                              │                              │
│                              ▼                              │
│                       review_agent                          │
│                              │                              │
│                              ▼                              │
│                       user_review ──► finalizer             │
│                              │  (needs_revision)            │
│                              └──── reanalyze ──► analyzers  │
└─────────────────────────┬───────────────────────────────────┘
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
│   ├── node_list.py             # Word 文档解析节点（python-docx）
│   └── test_analysis_nodes.py   # 5 个分析节点 + merge + review 节点
├── state/
│   └── state_list.py            # DocState：工作流全局状态定义
├── struct_output/
│   ├── output_list.py           # 数据模型：章节、测试点、聚合测试点
│   └── test_analysis_schema.py  # LLM 输出 schema（带 steps/expected_results）
├── prompt/
│   └── test_analysis/           # 6 个分析 prompt 模板
│       ├── table_analysis.py
│       ├── func_desc_analysis.py
│       ├── business_rule_analysis.py
│       ├── exception_analysis.py
│       ├── process_analysis.py
│       └── review_agent.py
├── static/                      # 上传的 .docx 源文件
├── .env                         # 环境变量（API Key、LangSmith 配置）
└── README.md
```

## 前端交互流程

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

## 环境变量

| 变量名 | 说明 | 示例 |
|--------|------|------|
| `GLM_API_KEY` | 智谱 AI API Key | `xxx.CqRJwzvxkMCi1RWX` |
| `GLM_BASE_URL` | 智谱 API 地址 | `https://open.bigmodel.cn/api/coding/paas/v4` |
| `GLM_MODEL` | 模型名称 | `GLM-4.7-Flash` |
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
