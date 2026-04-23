
from langchain_openai import ChatOpenAI
from state.state_list import AgentState, OverallState
from struct_output.output_list import IntentProgress, ParsedDoc

llm = ChatOpenAI()
parse_struct_llm = llm.with_structured_output(ParsedDoc)

# word文档解析
def parser_agent(state: OverallState):
    result = parse_struct_llm.invoke() # type: ignore
    return {"struct_data": result}


