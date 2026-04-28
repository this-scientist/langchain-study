-- ============================================================================
-- 测试点分析系统 · 数据库 Schema
-- 目标数据库: PostgreSQL 15+
-- 说明:
--   1. 索引命名: idx_<表名简写>_<字段>
--   2. FK  命名: fk_<从表>_<主表>
--   3. 所有主键使用 UUID，由应用层生成
--   4. JSONB 字段用于存储可变长度数组/嵌套对象 (steps, expected_results 等)
-- ============================================================================

-- 启用 UUID 扩展
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";


-- ============================================================================
--  第 1 部分: 文档解析库 (Parsed Document Store)
--  对应原 DocState 中的 parsed_data / sections / tables / function_sections
-- ============================================================================

-- 1.1 文档表
CREATE TABLE documents (
    id             UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    file_name      TEXT        NOT NULL,                  -- 原始文件名
    file_path      TEXT,                                  -- 服务器存储路径
    file_size      BIGINT,                                -- 文件大小 (bytes)
    status         TEXT        NOT NULL DEFAULT 'parsed', -- parsed / archived
    total_sections INT         NOT NULL DEFAULT 0,        -- 章节总数
    total_tables   INT         NOT NULL DEFAULT 0,        -- 表格总数
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_docs_status ON documents(status);


-- 1.2 文档章节表 (对应 DocSectionWithMetadata)
CREATE TABLE document_sections (
    id               UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    document_id      UUID    NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    section_index    INT     NOT NULL,                    -- 在文档中的顺序 (从 0 开始)

    title            TEXT    NOT NULL,                    -- 完整章节标题
    level            INT     NOT NULL DEFAULT 3,          -- 标题层级
    content          TEXT    NOT NULL,                    -- 章节正文

    meta_level_1     TEXT,                                -- 一级标题 (大模块)
    meta_level_2     TEXT,                                -- 二级标题
    meta_level_3     TEXT,                                -- 三级标题
    meta_level_4     TEXT,                                -- 四级标题

    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),

    UNIQUE (document_id, section_index)
);

CREATE INDEX idx_sec_doc  ON document_sections(document_id);
CREATE INDEX idx_sec_meta ON document_sections(document_id, meta_level_1, meta_level_2);


-- 1.3 章节表格表 (对应 TableData, 挂在 DocSectionWithMetadata.tables 下)
CREATE TABLE section_tables (
    id             UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    section_id     UUID    NOT NULL REFERENCES document_sections(id) ON DELETE CASCADE,
    table_index    INT     NOT NULL,                      -- 在该章节中的表格序号

    headers        JSONB   NOT NULL DEFAULT '[]',         -- ["列1","列2",...]
    rows           JSONB   NOT NULL DEFAULT '[]',         -- [["行1列1","行1列2"],...]
    caption        TEXT,                                  -- 表格标题/说明

    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),

    UNIQUE (section_id, table_index)
);

CREATE INDEX idx_stab_sec ON section_tables(section_id);


-- 1.4 章节功能分类表 (对应 FunctionSection, 挂在 DocSectionWithMetadata.function_sections 下)
CREATE TABLE section_function_parts (
    id             UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    section_id     UUID    NOT NULL REFERENCES document_sections(id) ON DELETE CASCADE,
    part_index     INT     NOT NULL,                      -- 在该章节中的序号

    section_type   TEXT    NOT NULL,                      -- 功能描述 / 业务规则 / 操作权限 / 处理过程 / 异常处理
    content        TEXT    NOT NULL,                      -- 该功能部分的详细内容
    tables_json    JSONB   NOT NULL DEFAULT '[]',         -- 该功能部分包含的表格 [{headers:[],rows:[],caption:""}]

    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),

    UNIQUE (section_id, part_index)
);

CREATE INDEX idx_sfp_sec   ON section_function_parts(section_id);
CREATE INDEX idx_sfp_type  ON section_function_parts(section_id, section_type);


-- ============================================================================
--  第 2 部分: 分析任务 (Analysis Task Store)
--  对应原 DocState 中的 iteration_count / max_iterations / is_approved 等
-- ============================================================================

-- 2.1 分析任务表
CREATE TABLE analysis_tasks (
    id                    UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    document_id           UUID    NOT NULL REFERENCES documents(id) ON DELETE CASCADE,

    status                TEXT    NOT NULL DEFAULT 'pending',
    -- pending → running → format_reviewing → coverage_reviewing → completed
    -- 任一阶段可跳转至 failed

    selected_section_ids  JSONB   NOT NULL DEFAULT '[]',  -- 用户选中分析的章节 ID 列表
    iteration_count       INT     NOT NULL DEFAULT 0,
    max_iterations        INT     NOT NULL DEFAULT 3,

    error_message         TEXT,                           -- 失败原因

    created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at          TIMESTAMPTZ
);

CREATE INDEX idx_task_doc    ON analysis_tasks(document_id);
CREATE INDEX idx_task_status ON analysis_tasks(status);


-- ============================================================================
--  第 3 部分: 测试用例库 (Test Case Store)
--  对应原 AggregatedTestAnalysis / TestPoint / AggregatedTestPoint
-- ============================================================================

-- 3.1 聚合分析表 (按 source_type 拆分存储)
CREATE TABLE aggregated_analyses (
    id                UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    task_id           UUID    NOT NULL REFERENCES analysis_tasks(id) ON DELETE CASCADE,

    source_type       TEXT    NOT NULL,                   -- table / func_desc / business_rule / exception / process

    total_test_points INT     NOT NULL DEFAULT 0,
    total_fragments   INT     NOT NULL DEFAULT 0,
    coverage_analysis TEXT    NOT NULL DEFAULT '',

    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX idx_aa_task_type ON aggregated_analyses(task_id, source_type);


-- 3.2 原文片段表 (对应 SourceFragmentWithPoints)
CREATE TABLE source_fragments (
    id                UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    aggregated_analysis_id UUID NOT NULL REFERENCES aggregated_analyses(id) ON DELETE CASCADE,

    fragment_index    INT     NOT NULL,                   -- 片段序号
    section_title     TEXT    NOT NULL,                   -- 来源章节标题
    content           TEXT    NOT NULL,                   -- 原文内容片段

    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),

    UNIQUE (aggregated_analysis_id, fragment_index)
);

CREATE INDEX idx_sfrag_aa ON source_fragments(aggregated_analysis_id);


-- 3.3 测试点表 (核心表，扁平化)
CREATE TABLE test_points (
    id                       UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    task_id                  UUID    NOT NULL REFERENCES analysis_tasks(id) ON DELETE CASCADE,
    source_fragment_id       UUID    REFERENCES source_fragments(id) ON DELETE SET NULL,

    test_point_id            TEXT    NOT NULL,            -- 业务标识，如 "TP-TABLE-001"
    description              TEXT    NOT NULL,            -- 测试点描述

    source_section           TEXT    NOT NULL,            -- 来源章节标题
    source_type              TEXT    NOT NULL,            -- 来源分析类型 (与 aggregated_analyses.source_type 一致)
    source_content           TEXT    NOT NULL,            -- 原文片段内容
    source_fragment_index    INT     NOT NULL DEFAULT 0,  -- 原文片段在分析中的索引

    priority                 TEXT    NOT NULL DEFAULT '中',  -- 高 / 中 / 低
    test_type                TEXT    NOT NULL DEFAULT '功能测试', -- 功能测试/边界测试/异常测试/权限测试

    steps                    JSONB   NOT NULL DEFAULT '[]',        -- ["1. 打开页面","2. 点击按钮","3. 观察结果"]
    expected_results         JSONB   NOT NULL DEFAULT '[]',        -- ["1. 页面正常显示","2. 按钮响应","3. 结果正确"]

    -- 格式审查字段
    format_valid             BOOLEAN,                              -- NULL=未审查, TRUE=合格, FALSE=不合格
    format_issues            JSONB,                                -- [{field:"steps",issue:"步骤与预期数量不匹配"}]
    auto_filled_fields       JSONB,                                -- 格式审查 Agent 自动补充的字段 {priority:"高",test_type:"边界测试"}

    created_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at               TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_tp_task     ON test_points(task_id);
CREATE INDEX idx_tp_source   ON test_points(task_id, source_type);
CREATE INDEX idx_tp_priority ON test_points(task_id, priority);
CREATE INDEX idx_tp_format   ON test_points(task_id, format_valid);


-- ============================================================================
--  第 4 部分: 格式审查 (Format Review)
--  检查步骤/预期结果是否一一对应，自动补充缺失字段
-- ============================================================================

CREATE TABLE format_review_results (
    id                    UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    task_id               UUID    NOT NULL REFERENCES analysis_tasks(id) ON DELETE CASCADE,

    total_test_points     INT     NOT NULL DEFAULT 0,
    format_valid_count    INT     NOT NULL DEFAULT 0,     -- 格式合格的测试点数
    format_invalid_count  INT     NOT NULL DEFAULT 0,     -- 格式不合格的测试点数
    auto_fixed_count      INT     NOT NULL DEFAULT 0,     -- 自动修复的测试点数

    issues_summary        JSONB   NOT NULL DEFAULT '[]',  -- 汇总问题 [{test_point_id, field, issue}]
    auto_fill_log         JSONB   NOT NULL DEFAULT '[]',  -- 自动填充日志 [{test_point_id, filled_fields:{}, reason:""}]

    reviewed_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_frev_task ON format_review_results(task_id);


-- ============================================================================
--  第 5 部分: 覆盖度审查 (Coverage Review)
--  读取用例库 + 解析文档库，检查需求分析覆盖是否完整
-- ============================================================================

CREATE TABLE coverage_review_results (
    id                    UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    task_id               UUID    NOT NULL REFERENCES analysis_tasks(id) ON DELETE CASCADE,

    completeness_score    FLOAT   NOT NULL DEFAULT 0,     -- 完整性评分 0-1
    accuracy_score        FLOAT   NOT NULL DEFAULT 0,     -- 准确性评分 0-1

    issues                JSONB   NOT NULL DEFAULT '[]',  -- 发现的问题 ["问题1","问题2"]
    suggestions           JSONB   NOT NULL DEFAULT '[]',  -- 改进建议 ["建议1","建议2"]
    missing_test_points   JSONB   NOT NULL DEFAULT '[]',  -- 遗漏的测试点 [{description, reason}]
    missing_areas         JSONB   NOT NULL DEFAULT '[]',  -- 遗漏的功能区域 ["权限校验","并发处理"]

    coverage_analysis     TEXT    NOT NULL DEFAULT '',    -- 覆盖率分析文本

    reviewed_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_crev_task ON coverage_review_results(task_id);


-- ============================================================================
--  第 6 部分: 覆盖度缺口表 (Coverage Gap Detail)
--  将 missed_areas 和无测试点覆盖的章节具象化存储
-- ============================================================================

CREATE TABLE coverage_gaps (
    id                    UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    review_id             UUID    NOT NULL REFERENCES coverage_review_results(id) ON DELETE CASCADE,
    task_id               UUID    NOT NULL REFERENCES analysis_tasks(id) ON DELETE CASCADE,

    gap_type              TEXT    NOT NULL,                -- uncovered_section / missing_scenario / weak_coverage
    section_id            UUID    REFERENCES document_sections(id) ON DELETE SET NULL,
    section_title         TEXT,                            -- 冗余字段，便于查询
    function_part_type    TEXT,                            -- 如果是某个功能分类遗漏，记录其类型
    description           TEXT    NOT NULL,                -- 缺口描述

    suggested_test_points JSONB   NOT NULL DEFAULT '[]',  -- Agent 建议补充的测试点

    created_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_cgap_review ON coverage_gaps(review_id);
CREATE INDEX idx_cgap_task   ON coverage_gaps(task_id);


-- ============================================================================
--  视图: 便于外部查询的常用视图
-- ============================================================================

-- 视图 1: 文档概览 (每个文档的章节/表格/功能分类统计)
CREATE VIEW v_document_overview AS
SELECT
    d.id              AS document_id,
    d.file_name,
    d.status,
    d.total_sections,
    d.total_tables,
    COUNT(DISTINCT ds.id)                 AS actual_sections,
    COUNT(DISTINCT st.id)                 AS actual_tables,
    COUNT(DISTINCT sfp.id)                AS actual_function_parts,
    jsonb_object_agg(
        sfp.section_type,
        COUNT(sfp.id)
    ) FILTER (WHERE sfp.section_type IS NOT NULL) AS function_part_distribution,
    d.created_at
FROM documents d
LEFT JOIN document_sections    ds  ON ds.document_id  = d.id
LEFT JOIN section_tables       st  ON st.section_id   = ds.id
LEFT JOIN section_function_parts sfp ON sfp.section_id = ds.id
GROUP BY d.id;


-- 视图 2: 任务测试点汇总 (按任务查看所有测试点及格式状态)
CREATE VIEW v_task_test_points AS
SELECT
    at.id               AS task_id,
    at.status           AS task_status,
    d.file_name         AS document_name,
    tp.id               AS test_point_db_id,
    tp.test_point_id,
    tp.description,
    tp.priority,
    tp.test_type,
    tp.source_type,
    tp.source_section,
    tp.format_valid,
    jsonb_array_length(tp.steps)          AS steps_count,
    jsonb_array_length(tp.expected_results) AS expected_count,
    tp.created_at
FROM test_points tp
JOIN analysis_tasks at ON at.id = tp.task_id
JOIN documents d       ON d.id  = at.document_id;


-- 视图 3: 覆盖度审查全貌
CREATE VIEW v_coverage_full AS
SELECT
    at.id                     AS task_id,
    d.file_name,
    cr.completeness_score,
    cr.accuracy_score,
    cr.missing_areas,
    jsonb_array_length(cr.missing_test_points) AS missing_tp_count,
    jsonb_array_length(cr.issues)              AS issue_count,
    COUNT(cg.id) FILTER (WHERE cg.id IS NOT NULL) AS gap_detail_count,
    cr.reviewed_at
FROM analysis_tasks at
JOIN documents d               ON d.id  = at.document_id
LEFT JOIN coverage_review_results cr ON cr.task_id = at.id
LEFT JOIN coverage_gaps        cg ON cg.task_id = at.id
GROUP BY at.id, d.file_name, cr.completeness_score, cr.accuracy_score,
         cr.missing_areas, cr.missing_test_points, cr.issues, cr.reviewed_at;


-- ============================================================================
--  触发器: 自动更新 updated_at
-- ============================================================================

CREATE OR REPLACE FUNCTION update_timestamp()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_documents_updated
    BEFORE UPDATE ON documents
    FOR EACH ROW EXECUTE FUNCTION update_timestamp();

CREATE TRIGGER trg_analysis_tasks_updated
    BEFORE UPDATE ON analysis_tasks
    FOR EACH ROW EXECUTE FUNCTION update_timestamp();

CREATE TRIGGER trg_test_points_updated
    BEFORE UPDATE ON test_points
    FOR EACH ROW EXECUTE FUNCTION update_timestamp();
