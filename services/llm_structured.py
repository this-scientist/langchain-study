import json
import os
import re
import time
from typing import TypeVar

from langchain_openai import ChatOpenAI
from pydantic import BaseModel

TStructured = TypeVar("TStructured", bound=BaseModel)


def _get_llm(temperature: float) -> ChatOpenAI:
    return ChatOpenAI(
        model=os.environ["GLM_MODEL"],
        temperature=temperature,
        api_key=os.environ["GLM_API_KEY"],
        base_url=os.environ["GLM_BASE_URL"],
    )


def invoke_structured(
    prompt_text: str,
    output_cls: type[TStructured],
    *,
    temperature: float = 0.3,
) -> TStructured:
    """Call LLM with JSON output, strip markdown fences, validate with pydantic."""
    llm = _get_llm(temperature)
    last_error = None
    for attempt in range(3):
        try:
            raw = llm.invoke(prompt_text)
            content = raw.content.strip() if raw.content else ""
            if not content:
                raise ValueError("LLM 返回空内容")

            content = re.sub(r"^```(?:markdown|json|)\s*", "", content)
            content = re.sub(r"\s*```$", "", content)
            content = content.strip()
            data = json.loads(content)
            return output_cls.model_validate(data)
        except Exception as e:
            last_error = e
            if attempt < 2:
                time.sleep(1 * (attempt + 1))
                continue
            raise last_error
