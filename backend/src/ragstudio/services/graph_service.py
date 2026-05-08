from ragstudio.schemas.graph import GraphOut
from ragstudio.services.adapter import RAGAnythingAdapter


class GraphService:
    def __init__(self, adapter: RAGAnythingAdapter | None = None):
        self.adapter = adapter or RAGAnythingAdapter()

    async def get_graph(self) -> GraphOut:
        graph = await self.adapter.graph()
        return GraphOut(nodes=list(graph.get("nodes") or []), edges=list(graph.get("edges") or []))
