from langchain_core.tools import tool

@tool
def execute_shell_command(command:  str):
    