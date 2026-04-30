"""按用户反馈对已有测试点做反思式重生成。"""

REGENERATE_WITH_FEEDBACK_PROMPT = """你是一名资深银行/企业级软件测试设计师。用户已有一条测试点与对应需求片段，并提出了改进要求。请在覆盖需求的前提下输出**改进后**的测试点列表。

## 用户改进要求
{user_instruction}

## 需求片段类型
{part_section_type}

## 需求片段正文
{part_content}

## 当前测试点（将被新版本取代；请吸收其中合理步骤并修正问题）
{current_tp_json}

请输出一个 JSON 对象，且**仅**输出该 JSON（不要 Markdown 围栏），结构为：
{{"test_points": [{{"test_point_id": "字符串", "description": "字符串", "priority": "高|中|低", "test_type": "规则验证|场景验证|流程验证|界面验证", "case_nature": "正|反", "steps": ["步骤1", "..."], "expected_results": ["预期1", "..."]}}]}}
至少包含 1 条测试点；步骤与预期条数宜对应。
"""
