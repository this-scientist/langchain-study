from langchain.chat_models import init_chat_model
from typing_extensions import Annotated, TypedDict
from typing import Optional
api_key = "在此处填写个人的 DeepSeek API key。"

model = init_chat_model("deepseek", model_provider="deepseek", api_key=api_key)

class Joke(TypedDict):
    """Joke to tell user."""

    setup: Annotated[str, ..., "The setup of the joke"]

    # Alternatively, we could have specified setup as:

    # setup: str                    # no default, no description
    # setup: Annotated[str, ...]    # no default, no description
    # setup: Annotated[str, "foo"]  # default, no description

    punchline: Annotated[str, ..., "The punchline of the joke"]
    rating: Annotated[Optional[int], None, "How funny the joke is, from 1 to 10"]


struct_LLM = model.with_structured_output(Joke)



struct_LLM.invoke()



model.invoke()