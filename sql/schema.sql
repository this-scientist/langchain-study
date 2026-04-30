-- ============================================================================
--  LangChain Study - 数据库初始化脚本 (PostgreSQL 13+)
-- ============================================================================

-- 开启扩展 (如果尚未开启)
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- 清理旧表 (按依赖顺序删除)
DROP VIEW IF EXISTS v_coverage_full CASCADE;
DROP VIEW IF EXISTS v_task_test_points CASCADE;
DROP VIEW IF EXISTS v_document_overview CASCADE;

DROP TABLE IF EXISTS coverage_gaps CASCADE;
DROP TABLE IF EXISTS coverage_review_results CASCADE;
DROP TABLE IF EXISTS format_review_results CASCADE;
DROP TABLE IF EXISTS test_points CASCADE;
DROP TABLE IF EXISTS regeneration_jobs CASCADE;
DROP TABLE IF EXISTS source_fragments CASCADE;
DROP TABLE IF EXISTS aggregated_analyses CASCADE;
DROP TABLE IF EXISTS analysis_tasks CASCADE;
DROP TABLE IF EXISTS section_function_parts CASCADE;
DROP TABLE IF EXISTS section_tables CASCADE;
DROP TABLE IF EXISTS document_sections CASCADE;
DROP TABLE IF EXISTS documents CASCADE;

-- ============================================================================
--  第 1 部分: 基础架构 (Document Store)
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

    selected_part_ids       JSONB   NOT NULL DEFAULT '[]',  -- section_function_parts.id 的 UUID 数组
    iteration_count       INT     NOT NULL DEFAULT 0,
    max_iterations        INT     NOT NULL DEFAULT 3,

    error_message         TEXT,                           -- 失败原因

    created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at          TIMESTAMPTZ
);

CREATE INDEX idx_task_doc    ON analysis_tasks(document_id);
CREATE INDEX idx_task_status ON analysis_tasks(status);


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


-- ============================================================================
--  第 3 部分: 测试用例库 (Test Case Store)
--  对应原 AggregatedTestAnalysis / TestPoint / AggregatedTestPoint
-- ============================================================================

-- 3.1 测试点表 (核心表，扁平化)
CREATE TABLE test_points (
    id                       UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    task_id                  UUID    NOT NULL REFERENCES analysis_tasks(id) ON DELETE CASCADE,
    function_part_id         UUID    NOT NULL REFERENCES section_function_parts(id) ON DELETE CASCADE,

    test_point_id            TEXT    NOT NULL,            -- 业务标识，如 "TP-TABLE-001"
    description              TEXT    NOT NULL,            -- 测试点描述

    priority                 TEXT    NOT NULL DEFAULT '中',  -- 高 / 中 / 低
    test_type                TEXT    NOT NULL DEFAULT '规则验证', -- 规则验证/场景验证/流程验证/界面验证
    case_nature              TEXT    NOT NULL DEFAULT '正', -- 用例性质：正/反

    -- 用例分类字段
    transaction_name         TEXT,                        -- 所属交易（2级标题）
    test_case_path           TEXT,                        -- 测试用例目录（2级标题\3级标题）

    steps                    JSONB   NOT NULL DEFAULT '[]',        -- ["1. 打开页面","2. 点击按钮","3. 观察结果"]
    expected_results         JSONB   NOT NULL DEFAULT '[]',        -- ["1. 页面正常显示","2. 按钮响应","3. 结果正确"]

    -- 格式审查字段
    format_valid             BOOLEAN,                              -- NULL=未审查, TRUE=合格, FALSE=不合格
    format_issues            JSONB,                                -- [{field:"steps",issue:"步骤与预期数量不匹配"}]

    -- 软删除字段
    is_deleted               BOOLEAN NOT NULL DEFAULT FALSE,

    replaces_id                  UUID REFERENCES test_points(id) ON DELETE SET NULL,
    regeneration_job_id          UUID REFERENCES regeneration_jobs(id) ON DELETE SET NULL,
    user_feedback_at_regenerate  TEXT,

    created_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at               TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_tp_task     ON test_points(task_id);
CREATE INDEX idx_tp_func_part ON test_points(function_part_id);
CREATE INDEX idx_tp_priority ON test_points(task_id, priority);
CREATE INDEX idx_tp_format   ON test_points(task_id, format_valid);


-- ============================================================================
--  第 4 部分: 格式审查 (Format Review)
--  记录每一个存在问题的 test_points 和存在问题的点
-- ============================================================================

CREATE TABLE format_review_results (
    id                    UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    task_id               UUID    NOT NULL REFERENCES analysis_tasks(id) ON DELETE CASCADE,
    test_point_id         UUID    NOT NULL REFERENCES test_points(id) ON DELETE CASCADE,

    field                 TEXT    NOT NULL,               -- 有问题的字段: steps / expected_results / priority / test_type
    issue                 TEXT    NOT NULL,               -- 具体问题描述
    suggestion            TEXT,                           -- 改进建议

    reviewed_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_frev_task ON format_review_results(task_id);
CREATE INDEX idx_frev_tp   ON format_review_results(test_point_id);


-- ============================================================================
--  视图: 便于外部查询的常用视图
-- ============================================================================

-- 视图 1: 文档概览 (每个文档的章节/表格/功能分类统计)
CREATE VIEW v_document_overview AS
WITH function_counts AS (
    SELECT 
        ds.document_id,
        sfp.section_type,
        COUNT(sfp.id) as type_count
    FROM document_sections ds
    JOIN section_function_parts sfp ON sfp.section_id = ds.id
    GROUP BY ds.document_id, sfp.section_type
),
function_distribution AS (
    SELECT 
        document_id,
        jsonb_object_agg(section_type, type_count) as distribution
    FROM function_counts
    GROUP BY document_id
)
SELECT
    d.id              AS document_id,
    d.file_name,
    d.status,
    d.total_sections,
    d.total_tables,
    COUNT(DISTINCT ds.id)                 AS actual_sections,
    COUNT(DISTINCT st.id)                 AS actual_tables,
    COUNT(DISTINCT sfp.id)                AS actual_function_parts,
    fd.distribution                       AS function_part_distribution,
    d.created_at
FROM documents d
LEFT JOIN document_sections    ds  ON ds.document_id  = d.id
LEFT JOIN section_tables       st  ON st.section_id   = ds.id
LEFT JOIN section_function_parts sfp ON sfp.section_id = ds.id
LEFT JOIN function_distribution fd  ON fd.document_id = d.id
GROUP BY d.id, fd.distribution;


-- 视图 2: 任务测试点汇总 (关联原文信息)
CREATE VIEW v_task_test_points AS
SELECT
    at.id               AS task_id,
    at.status           AS task_status,
    d.file_name         AS document_name,
    sfp.section_type    AS source_type,
    ds.title            AS source_section,
    sfp.content         AS source_content,
    tp.id               AS test_point_db_id,
    tp.test_point_id,
    tp.description,
    tp.priority,
    tp.test_type,
    tp.format_valid,
    jsonb_array_length(tp.steps)          AS steps_count,
    jsonb_array_length(tp.expected_results) AS expected_count,
    tp.created_at
FROM test_points tp
JOIN analysis_tasks at ON at.id = tp.task_id
JOIN documents d       ON d.id  = at.document_id
JOIN section_function_parts sfp ON sfp.id = tp.function_part_id
JOIN document_sections ds ON ds.id = sfp.section_id;


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

CREATE TRIGGER trg_regeneration_jobs_updated
    BEFORE UPDATE ON regeneration_jobs
    FOR EACH ROW EXECUTE FUNCTION update_timestamp();
