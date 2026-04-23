
from langchain_openai import ChatOpenAI
from state.state_list import AgentState, OverallState, DocState
from struct_output.output_list import IntentProgress, ParsedDoc
from langchain_core.documents import Document
from langchain_openai import OpenAIEmbeddings
from langchain_chroma import Chroma

llm = ChatOpenAI()
parse_struct_llm = llm.with_structured_output(ParsedDoc)

# word文档解析
def parser_agent(state: OverallState):
    result = parse_struct_llm.invoke() # type: ignore
    return {"struct_data": result}


def word_indexer_node(state: DocState):
    """word数据加入向量库"""
    sections = state["parsed_data"].sections
    documents = []
    
    for sec in sections:
        # 将标题和正文组合，增强检索时的语义匹配
        combined_text = f"标题：{sec.title}\n内容：{sec.content}"
        # 存储元数据，方便以后按层级过滤
        metadata = {"title": sec.title, "level": sec.level}
        documents.append(Document(page_content=combined_text, metadata=metadata))
    
    # 存入本地向量库
    db = Chroma.from_documents(documents, OpenAIEmbeddings())
    db.("word_index")
    return {"index_status": "Completed"}