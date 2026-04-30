import json
from unittest.mock import MagicMock, patch

import pytest

from struct_output.test_analysis_schema import SinglePartAnalysisResult


@pytest.fixture(autouse=True)
def _glm_env(monkeypatch):
    monkeypatch.setenv("GLM_API_KEY", "test-key")
    monkeypatch.setenv("GLM_BASE_URL", "http://test")
    monkeypatch.setenv("GLM_MODEL", "test-model")


def test_invoke_structured_parses_json_and_validates():
    from services.llm_structured import invoke_structured

    minimal = {"test_points": [{"test_point_id": "TP-1", "description": "示例"}]}
    mock_llm = MagicMock()
    mock_llm.invoke.return_value = MagicMock(content=json.dumps(minimal))

    with patch("services.llm_structured.ChatOpenAI", return_value=mock_llm):
        result = invoke_structured("prompt", SinglePartAnalysisResult)

    assert isinstance(result, SinglePartAnalysisResult)
    assert result.test_points[0].test_point_id == "TP-1"


def test_invoke_structured_strips_markdown_fences():
    from services.llm_structured import invoke_structured

    minimal = {"test_points": [{"test_point_id": "TP-F", "description": "fenced"}]}
    body = "```json\n" + json.dumps(minimal) + "\n```"

    mock_llm = MagicMock()
    mock_llm.invoke.return_value = MagicMock(content=body)

    with patch("services.llm_structured.ChatOpenAI", return_value=mock_llm):
        result = invoke_structured("prompt", SinglePartAnalysisResult)

    assert isinstance(result, SinglePartAnalysisResult)
