from langchain_openai import ChatOpenAI
from state.state_list import AgentState, OverallState, DocState
from struct_output.output_list import IntentProgress
from langchain_community.document_loaders import UnstructuredWordDocumentLoader


def loader_doc(state: DocState):
    """加载word"""
    loader = UnstructuredWordDocumentLoader(state["file_path"], mode="elements")
    docs = loader.load()

    chunks = [d.page_content for d in docs]
    return {"raw_text_chunks": chunks}