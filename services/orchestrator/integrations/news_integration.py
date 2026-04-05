"""
Samantha OS — News Integration
Aggregates news via RSS feeds — free, no API key, configurable sources.
"""

from __future__ import annotations
import logging
import xml.etree.ElementTree as ET
from html import unescape
import re

import httpx

from integrations import BaseIntegration, IntegrationAction

logger = logging.getLogger("samantha.news")

DEFAULT_FEEDS = {
    "tech":    "https://feeds.arstechnica.com/arstechnica/index",
    "world":   "http://feeds.bbci.co.uk/news/world/rss.xml",
    "science": "https://rss.nytimes.com/services/xml/rss/nyt/Science.xml",
    "ai":      "https://techcrunch.com/category/artificial-intelligence/feed/",
    "sweden":  "https://www.svt.se/nyheter/rss.xml",
}


def strip_html(text: str) -> str:
    clean = re.sub(r'<[^>]+>', '', unescape(text or ""))
    return re.sub(r'\s+', ' ', clean).strip()


class NewsIntegration(BaseIntegration):
    name = "news"
    display_name = "News (RSS)"
    description = "Latest news headlines from configurable RSS sources"
    icon = "📰"
    requires_auth = False

    def __init__(self):
        super().__init__()
        self.feeds: dict[str, str] = {}

    async def initialize(self, config: dict) -> bool:
        self.feeds = config.get("feeds", DEFAULT_FEEDS)
        return True

    def get_actions(self) -> list[IntegrationAction]:
        categories = ", ".join(self.feeds.keys())
        return [
            IntegrationAction(
                name="headlines",
                description=f"Get latest news headlines. Categories: {categories}",
                keywords=["news", "headlines", "happening", "latest", "current events", "whats going on", "tell me about today"],
                parameters=["category", "count"],
                examples=["What's in the news?", "Any tech news?", "Give me the headlines", "What is happening in the world?", "Any news today?"],
            ),
        ]

    async def execute(self, action_name: str, params: dict) -> dict:
        category = params.get("category", "").lower()
        count = params.get("count", 5)

        if category and category in self.feeds:
            feeds_to_fetch = {category: self.feeds[category]}
        elif category:
            return {"error": f"Unknown category. Available: {', '.join(self.feeds.keys())}"}
        else:
            feeds_to_fetch = self.feeds

        all_items = []
        async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
            for cat, url in feeds_to_fetch.items():
                try:
                    resp = await client.get(url)
                    root = ET.fromstring(resp.content)
                    # Handle both RSS 2.0 and Atom
                    items = root.findall(".//item") or root.findall(".//{http://www.w3.org/2005/Atom}entry")
                    for item in items[:count]:
                        title = item.findtext("title") or item.findtext("{http://www.w3.org/2005/Atom}title") or ""
                        desc = item.findtext("description") or item.findtext("{http://www.w3.org/2005/Atom}summary") or ""
                        link = item.findtext("link") or ""
                        if not link:
                            link_el = item.find("{http://www.w3.org/2005/Atom}link")
                            link = link_el.get("href", "") if link_el is not None else ""
                        pub = item.findtext("pubDate") or item.findtext("{http://www.w3.org/2005/Atom}published") or ""

                        all_items.append({
                            "title": strip_html(title),
                            "summary": strip_html(desc)[:500],
                            "link": link.strip(),
                            "published": pub,
                            "category": cat,
                        })
                except Exception as e:
                    logger.warning(f"Failed to fetch {cat} feed: {e}")

        # Sort by most recent (rough — pub date formats vary)
        all_items = all_items[:count * 2]  # Limit total

        return {"headlines": all_items[:count], "sources": list(feeds_to_fetch.keys())}

    def get_context_for_llm(self) -> str | None:
        cats = ", ".join(self.feeds.keys())
        return f"You can fetch news headlines. Available categories: {cats}."
