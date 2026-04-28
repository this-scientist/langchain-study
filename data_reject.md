# 工作流数据传递追踪（Data Flow Trace）

> 分析 LangGraph 工作流中，每个节点的输入/输出及 state 合并机制。

## 一、整体拓扑

```
increment_iteration
    │ 输出: {iteration_count: N}
    ▼
analysis_coordinator
    │ 输出: {aggregated_analysis: dict|None}
    ▼
review_agent
    │ 输出: {approval_feedback: dict|None, is_approved: bool}
    ▼
user_review  ───条件判断──→ approved ──→ finalizer ──→ END
    │                      needs_revision ──→ increment_iteration (循环)
    │                      max_reached ──→ finalizer ──→ END
```

## 二、LangGraph State 合并机制

**每个节点接收全量 state（DocState TypedDict），只返回要更新的键，LangGraph 执行 `state.update(return_dict)` 合并。**

```
节点B的输入 = 节点A输出 ←┐
    ├─ state["key1"] = 初始值      │
    ├─ state["key2"] = 旧值状态     ├─ LangGraph 合并
    └─ state["aggregated"] = 新值  ┘
```

---

## 三、逐节点数据流追踪

### 节点 1：increment_iteration

| 项目 | 内容 |
|---|---|
| **注册名** | `"increment_iteration"` |
| **函数** | `increment_iteration_node` |
| **输入** | `state` — 初始 DocState（或上一轮循环后的 state） |
| **读取字段** | `state["iteration_count"]` |
| **返回** | `{"iteration_count": N+1}` |
| **合并后 state 关键字段** | `iteration_count` 变为 N+1，其余字段不变 |

**示例（首次执行）：**
```
输入 state:  { iteration_count: 0, aggregated_analysis: None, ... }
返回 dict:   { iteration_count: 1 }
合并后 state: { iteration_count: 1, aggregated_analysis: None, ... }
```

---

### 节点 2：analysis_coordinator

| 项目 | 内容 |
|---|---|
| **注册名** | `"analysis_coordinator"` |
| **函数** | `analysis_coordinator_node` |
| **输入** | 合并后的 state（含 `iteration_count: 1`） |
| **读取字段** | `state["parsed_data"]`、`state["selected_section_indices"]` |
| **返回** | `{"aggregated_analysis": dict | None}` |

#### 内部调用链（非LangGraph节点，纯Python函数调用）

```
analysis_coordinator_node(state)
    ├── table_analysis_node(state)
    │     ├── _get_selected_sections(state)  → List[DocSectionWithMetadata]
    │     ├── _collect_table_data(sections)  → List[Tuple[str, TableData]]
    │     ├── LLM.invoke(prompt)             → raw JSON
    │     ├── _invoke_structured()           → AnalysisResult
    │     ├── _build_aggregated_analysis()   → AggregatedTestAnalysis (Pydantic)
    │     └── return {"table_aggregated": AggregatedTestAnalysis | None}
    │
    ├── func_desc_analysis_node(state)
    │     ├── 同上模式 ...
    │     └── return {"func_desc_aggregated": AggregatedTestAnalysis | None}
    │
    ├── business_rule_analysis_node(state)
    │     └── return {"business_rule_aggregated": ...}
    │
    ├── exception_analysis_node(state)
    │     └── return {"exception_aggregated": ...}
    │
    └── process_analysis_node(state)
          └── return {"process_aggregated": ...}
    
    关键：这些子函数返回的 Dict **不会**被 LangGraph 合并到 state！
         它们的返回值仅在 analysis_coordinator_node 内部使用。
    
    ↓ 然后 analysis_coordinator_node 自己汇总：
    merged = _merge_aggregated_analyses([有数据的分析结果])
    return {"aggregated_analysis": merged.model_dump() 或 None}
```

#### 临界问题 1：子分析节点返回的 state_key 从不进入 LangGraph State

```
table_analysis_node 返回 {"table_aggregated": data}
                                    ↑
                        仅在此函数内部访问
                        analysis_coordinator 用 ret.get("table_aggregated") 取走
                        LangGraph 完全不知道这个 key 的存在

→ 结论：table_aggregated / func_desc_aggregated / ... 
   在 LangGraph State 中永远是 None（初始值），从未被更新
```

**举例验证：**
```
第1轮: analysis_coordinator 返回 {"aggregated_analysis": None}
第2轮: increment_iteration → analysis_coordinator 再次被调用
       state["table_aggregated"]     → None （从未被更新过）
       state["func_desc_aggregated"] → None （从未被更新过）
```

#### 临界问题 2：所有子分析失败时 aggregated_analysis = None

```
全部子分析返回 None → merged = None
→ return {"aggregated_analysis": None}
→ review_agent 收到 aggregated_analysis = None
→ 跳过审核 → user_review 也跳过
→ should_continue 判断 iteration_count < max_iterations
→ 回到 increment_iteration → 重新执行一轮
```

**合并后 state 关键字段：**
```
aggregated_analysis: dict | None    ← 仅此一个键被更新
其余所有分析字段: 保持初始 None       ← 子分析返回值未进 state
```

---

### 节点 3：review_agent

| 项目 | 内容 |
|---|---|
| **注册名** | `"review_agent"` |
| **函数** | `review_agent_node` |
| **输入** | 合并后的 state（含 `aggregated_analysis: dict` 或 `None`） |
| **读取字段** | `state["aggregated_analysis"]` |
| **返回** | `{"approval_feedback": dict | None, "is_approved": bool}` |

**正常路径（有数据）：**
```
输入 aggregated_analysis = { fragments: [...], total_test_points: N, ... }
  ↓ 解析 fragments 构造提示词
  ↓ LLM 审核 → ReviewResult
返回 { approval_feedback: {...}, is_approved: true/false }
```

**异常路径（无数据）：**
```
输入 aggregated_analysis = None
  ↓ 直接返回 early
返回 { approval_feedback: None, is_approved: False }
```

**合并后 state 关键字段：**
```
aggregated_analysis: 不变（保持上一节点写入的值）
approval_feedback:  dict | None
is_approved:        bool
```

---

### 节点 4：user_review

| 项目 | 内容 |
|---|---|
| **注册名** | `"user_review"` |
| **函数** | `user_review_node` |
| **输入** | 合并后的 state（含 `aggregated_analysis` + `approval_feedback`） |
| **读取字段** | `state["aggregated_analysis"]` |
| **正常行为** | 调用 `interrupt()` 暂停，等待用户输入（y/修改意见） |
| **返回** | `{"user_review": UserReviewStatus, "user_interrupted": False}` |

**异常路径（aggregated_analysis 为空）：**
```
if not aggregated:
    return {"user_review": None, "user_interrupted": False}
    ↑ 不调用 interrupt() → 流程不会暂停 → 直接继续
```

**临界问题 3：全部子分析失败时，user_review 不 interrupt**

```
aggregated_analysis = None
→ user_review 不暂停
→ 返回 user_review = None
→ should_continue 判断：
    user_review = None → 不 approved
    iteration_count < max_iterations → "needs_revision"
    └── 回到 increment_iteration（死循环！直到 count >= max）
```

---

### 节点 5：should_continue（条件边）

| 项目 | 内容 |
|---|---|
| **类型** | `add_conditional_edges` 路由函数 |
| **输入** | 全量 state |
| **读取字段** | `state["is_cancelled"]`、`state["user_review"]`、`state["iteration_count"]`、`state["max_iterations"]` |
| **输出** | 字符串路由：`"approved"` / `"needs_revision"` / `"max_reached"` |

**路由逻辑：**
```
is_cancelled? → "max_reached"
aggregated_analysis 为空? → "max_reached"  ← 新增：无数据直接终止
user_review?.approved? → "approved"
iteration_count >= max_iterations? → "max_reached"
否则 → "needs_revision"
```

---

### 节点 6：finalizer

| 项目 | 内容 |
|---|---|
| **注册名** | `"finalizer"` |
| **函数** | `create_final_result` |
| **输入** | 最终合并后的 state |
| **读取字段** | `state["aggregated_analysis"]`、`state["approval_feedback"]`、`state["user_review"]`、`state["iteration_count"]` |
| **返回** | `{"test_analysis_result": TestAnalysisWithApproval | None}` |

**正常路径：**
```
aggregated_analysis != None 且 approval_feedback != None
  → 展平 fragments → 构造 TestPointAnalysis
  → 返回 TestAnalysisWithApproval
```

**异常路径：**
```
aggregated_analysis == None 或 approval_feedback == None
  → 返回 {"test_analysis_result": None}
```

---

## 四、全量 State 字段更新追踪表

| 字段 | 初始值 | 在哪个节点被更新 | 更新方式 | 备注 |
|---|---|---|---|---|
| `iteration_count` | 0 | `increment_iteration` | `count+1` | 每轮+1 |
| `aggregated_analysis` | None | `analysis_coordinator` | `model_dump()` 或 None | ⚠️ 子分析全失败则为 None |
| `approval_feedback` | None | `review_agent` | dict 或 None | ⚠️ 无数据时不调用 LLM，直接 None |
| `is_approved` | False | `review_agent` | bool | |
| `user_review` | None | `user_review_node` | UserReviewStatus 或 None | ⚠️ 无数据时不 interrupt，直接 None |
| `table_aggregated` | None | **永不更新** | — | ❌ 子函数返回值不进 LangGraph State |
| `func_desc_aggregated` | None | **永不更新** | — | ❌ 同上 |
| `business_rule_aggregated` | None | **永不更新** | — | ❌ 同上 |
| `exception_aggregated` | None | **永不更新** | — | ❌ 同上 |
| `process_aggregated` | None | **永不更新** | — | ❌ 同上 |
| `test_analysis_result` | None | `finalizer` | dict 或 None | ⚠️ 前序为 None 则最终 None |

---

## 五、当前系统的根本问题链

```
子分析节点（LLM 调用）
    │ 失败原因：字段名不匹配(id→test_point_id)、字段缺失(priority)、LLM 空响应
    ▼
5 个子分析全部返回 None
    │
    ▼
analysis_coordinator 返回 {"aggregated_analysis": None}
    │
    ├──→ review_agent 跳过（aggregated = None）→ approval_feedback = None
    ├──→ user_review 跳过（不 interrupt）→ user_review = None
    ├──→ should_continue → "needs_revision" → 回到 increment_iteration
    │       ↑ 死循环直到 iteration_count >= max_iterations
    │
    └──→ max_reached → finalizer → test_analysis_result = None
```

**问题定性：**
1. **`table_aggregated` 等 5 个字段在 LangGraph State 中永不更新** — 因为它们被 `analysis_coordinator_node` 内部调用，返回值仅内部使用，不进 state。虽然当前不影响功能（coordinator 直接用返回值汇总），但如果后续有节点想单独读这些字段，永远为 None。
2. **LLM 失败 → 全链路静默失败** — 没有重试或降级机制，pipeline 所有节点都走 early return
3. **User Review 无数据时流程静默循环** — `user_review_node` 提前返回 `user_review = None`，`should_continue` 检测到 `approved` 为 False 且未超最大迭代 → 继续循环

---

## 七、已修复（2026-04-28）

| # | 问题 | 修复方式 | 涉及文件 |
|---|---|---|---|
| **1** | `xxx_aggregated` 字段不在 State | `analysis_coordinator_node` 返回时追加 `**individual_results`，各子分析结果也被写入 LangGraph State | `test_analysis_nodes.py` |
| **2** | 全失败死循环 | `should_continue` 优先检查 `aggregated_analysis`，为空则直接 `"max_reached"` → `finalizer` | `test_analysis_workflow.py` |
| **3** | `user_review` 提前返回不 interrupt | 移除 `if not aggregated: return ...` 逻辑，始终触发 `interrupt()`，用户始终可控制流程 | `test_analysis_nodes.py` |

### 修复后的流程逻辑

```
analysis_coordinator
  ├─ 有数据 → return {aggregated_analysis: dict, table_aggregated: ..., ...}
  └─ 无数据 → return {aggregated_analysis: None, table_aggregated: None, ...}

should_continue
  ├─ aggregated_analysis 为空 → "max_reached"（跳出循环）
  ├─ 用户批准 → "approved"
  ├─ 超迭代 → "max_reached"
  └─ 驳回 → "needs_revision"（继续分析）

user_review
  └─ 始终 interrupt，展示真实数据量（可能为 0）
```

### 修复后的问题链对比

```
修复前：                                     修复后：
LLM 全失败                                    LLM 全失败
  ↓                                              ↓
aggregated = None                                aggregated = None
  ↓                                              ↓
review_agent 跳过                                review_agent 跳过
  ↓                                              ↓
user_review 不 interrupt                         user_review interrupt(0个测试点)
  ↓                                              ↓ 用户可批准或关闭
should_continue → "needs_revision"               should_continue → "max_reached"
  ↓                                              ↓
increment_iteration → 再来一轮...                finalizer → 结束
  ↓ 直到 max_iterations
```

---

## 六、示例：一次完整执行的 State 变化

### 场景：上传文档 → 分析 → 批准 → 结束

```
Step 0: 初始状态
  iteration_count=0, aggregated_analysis=None, 
  approval_feedback=None, user_review=None, is_approved=False

Step 1: increment_iteration → return {iteration_count: 1}
  iteration_count=1

Step 2: analysis_coordinator → 内部调用5个子分析
  假设 table 有数据，其他无数据：
  merged = _merge([table_aggregated])
  return {aggregated_analysis: dict(fragments=[...], total_test_points=5)}
  → state: aggregated_analysis=dict, iteration_count=1

Step 3: review_agent → 读取 aggregated_analysis
  LLM 审核 → approval_feedback=dict(is_approved=True)
  return {approval_feedback: dict, is_approved: True}
  → state: 新增 approval_feedback, is_approved

Step 4: user_review → 读取 aggregated_analysis
  interrupt() → 用户输入 "y"
  return {user_review: UserReviewStatus(approved=True), user_interrupted: False}

Step 5: should_continue
  user_review.approved=True → "approved" → finalizer

Step 6: finalizer
  aggregated_analysis ≠ None, approval_feedback ≠ None
  → 展平 → TestPointAnalysis → TestAnalysisWithApproval
  return {test_analysis_result: dict(analysis=..., approval=..., ...)}
  → END
```

### 场景：全部 LLM 分析失败（当前 bug 场景）

```
Step 0: iteration_count=0, 所有分析字段=None

Step 1: increment_iteration → iteration_count=1

Step 2: analysis_coordinator
  table → LLM 失败 → return None
  func_desc → LLM 失败 → return None
  ...全部失败
  0 个子分析有数据 → return {aggregated_analysis: None}
  → state: aggregated_analysis=None

Step 3: review_agent
  aggregated_analysis=None → 直接 return 
  → state: approval_feedback=None, is_approved=False

Step 4: user_review
  aggregated_analysis=None → 不 interrupt → 直接 return
  → state: user_review=None

Step 5: should_continue
  user_review=None → 不 approved
  iteration_count=1 < max=3 → "needs_revision"

Step 6: increment_iteration → iteration_count=2
Step 7-9: 同上 → 全部失败
Step 10: increment_iteration → iteration_count=3
Step 11-13: 同上 → 全部失败
Step 14: should_continue
  iteration_count=3 >= max=3 → "max_reached"

Step 15: finalizer
  aggregated_analysis=None AND approval_feedback=None
  → return {test_analysis_result: None}
  → END
  → 前端收到 status=completed, result=None
  → 页面展示不出测试点
```
