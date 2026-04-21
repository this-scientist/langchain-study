from langchain_core.tools import tool
from pydantic import BaseModel, Field
from dotenv import load_dotenv
load_dotenv()

class InputArg(BaseModel):
    a: int = Field(..., alias='a', description="")
    b: int = Field(..., alias='b', description="")

@tool("", args_schema=InputArg, return_direct=True)
def test_tool(a: int,b: int) :
    """ this is a test tool"""
    return a * b

print(test_tool.name)
print(test_tool.description)
print(test_tool.args)
print(test_tool.invoke({"a": 2, "b": 3}))