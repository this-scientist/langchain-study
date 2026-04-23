from langgraph.graph import StateGraph,END
from state.state_list import DocState
from node.file_loader import loader_doc
workflow = StateGraph(DocState)

workflow.add_node("loader", loader_doc)
