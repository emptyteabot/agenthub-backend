from app.agents.schemas import SearchOutput
from app.core.llm_client import AsyncLLMClient


async def run_search_agent(client: AsyncLLMClient, query: str) -> SearchOutput:
    return SearchOutput(
        summary=f"Mock search completed for: {query}",
        sources=["mock://search-agent"],
    )
