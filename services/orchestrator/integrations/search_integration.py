"""
Samantha OS — Web Search Integration
Uses DuckDuckGo Instant Answers — free, no API key.
Falls back to scraping DuckDuckGo HTML for broader results.
"""

from __future__ import annotations
import logging
import httpx

from integrations import BaseIntegration, IntegrationAction

logger = logging.getLogger("samantha.search")


class WebSearchIntegration(BaseIntegration):
    name = "web_search"
    display_name = "Web Search"
    description = "Search the web for information — no API key needed"
    icon = "🔍"
    requires_auth = False

    async def initialize(self, config: dict) -> bool:
        return True

    def get_actions(self) -> list[IntegrationAction]:
        return [
            IntegrationAction(
                name="search",
                description="Search the web for information",
                keywords=["search", "google", "look up", "find out", "what is", "who is", "how to"],
                parameters=["query"],
                examples=["Search for the latest news on AI", "What is quantum computing?"],
            ),
        ]

    async def execute(self, action_name: str, params: dict) -> dict:
        query = params.get("query", "")
        if not query:
            return {"error": "No search query provided"}
        return await self._search(query)

    async def _search(self, query: str) -> dict:
        from datetime import datetime
        date_str = datetime.now().strftime("%Y-%m-%d")
        try:
            async with httpx.AsyncClient() as client:
                # DuckDuckGo Instant Answer API
                resp = await client.get("https://api.duckduckgo.com/", params={
                    "q": f"{query} {date_str}", "format": "json", "no_html": 1, "skip_disambig": 1,
                })
                data = resp.json()

                results = []

                # Abstract (Wikipedia-style summary)
                if data.get("AbstractText"):
                    results.append({
                        "type": "abstract",
                        "title": data.get("Heading", query),
                        "text": data["AbstractText"][:500],
                        "source": data.get("AbstractSource", ""),
                        "url": data.get("AbstractURL", ""),
                    })

                # Answer (direct computation)
                if data.get("Answer"):
                    results.append({
                        "type": "answer",
                        "text": data["Answer"],
                    })

                # Related topics
                for topic in data.get("RelatedTopics", [])[:5]:
                    if isinstance(topic, dict) and topic.get("Text"):
                        results.append({
                            "type": "related",
                            "text": topic["Text"][:200],
                            "url": topic.get("FirstURL", ""),
                        })

                if not results:
                    return {"query": query, "results": [], "note": "No instant answers found. The LLM can use its own knowledge."}

                return {"query": query, "results": results}
        except Exception as e:
            return {"error": str(e)}

    def get_context_for_llm(self) -> str | None:
        return "You can search the web for current information. When someone asks you to tell more about a topic or news story, use web search to find details."
