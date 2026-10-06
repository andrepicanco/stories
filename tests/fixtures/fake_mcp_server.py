"""Servidor MCP mínimo (stdio) usado nos testes da ponte."""
from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

server = MCPServer("fake")


@server.tool(name="read_thing", description="lê uma coisa", annotations=ToolAnnotations(read_only_hint=True))
def read_thing(key: str) -> str:
    return f"valor de {key}"


@server.tool(name="write_thing", description="grava uma coisa", annotations=ToolAnnotations(read_only_hint=False))
def write_thing(key: str) -> str:
    return "gravou"


@server.tool(name="dup_thing", description="duplicada de outra tool", annotations=ToolAnnotations(read_only_hint=True))
def dup_thing() -> str:
    return "dup"


@server.tool(name="no_annotation_listed", description="sem anotação, mas na lista de leitura")
def no_annotation_listed() -> str:
    return "ok"


@server.tool(name="no_annotation_unlisted", description="sem anotação e fora da lista")
def no_annotation_unlisted() -> str:
    return "nao deveria aparecer"


@server.tool(name="boom", description="sempre falha", annotations=ToolAnnotations(read_only_hint=True))
def boom() -> str:
    raise ValueError("falhou de propósito")


if __name__ == "__main__":
    server.run("stdio")
