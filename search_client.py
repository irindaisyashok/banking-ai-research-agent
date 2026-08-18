"""
search_client.py
External Research / Data layer — Tavily search API (free tier, key-based,
purpose-built for AI research agents). Tavily returns already-extracted
page content, so a separate scrape step is only used as a fallback.

Swap-out note: if Tavily's free tier ever becomes unavailable, this is the
only file that needs to change — replace search_web() with another
provider (e.g. SerpAPI, Brave Search API) as long as it keeps returning the
same {title, url, snippet} shape that every other module depends on.
"""

import os
import requests
from bs4 import BeautifulSoup

try:
    from tavily import TavilyClient
except ImportError:
    TavilyClient = None

TAVILY_API_KEY = os.environ.get("TAVILY_API_KEY", "")
HEADERS = {"User-Agent": "Mozilla/5.0 (Enterprise AI Research Agent; +educational use)"}

_client = None


def _get_client():
    global _client
    if _client is None:
        if TavilyClient is None:
            raise RuntimeError("tavily-python is not installed. Run: pip install tavily-python")
        if not TAVILY_API_KEY:
            raise RuntimeError("TAVILY_API_KEY is not set. Add it to your .env file.")
        _client = TavilyClient(TAVILY_API_KEY)
    return _client


def search_web(query, max_results=5):
    """Returns a list of {title, url, snippet} dicts. 'snippet' here is
    Tavily's already-extracted page content, so it can usually be used
    directly for finding extraction without a separate page fetch."""
    results = []
    try:
        client = _get_client()
        response = client.search(query=query, search_depth="advanced", max_results=max_results)
        for r in response.get("results", []):
            results.append({
                "title": r.get("title", ""),
                "url": r.get("url", ""),
                "snippet": r.get("content", ""),
            })
    except Exception as e:
        print(f"[search_client] Tavily search failed for '{query}': {e}")
    return results


def fetch_page_text(url, max_chars=6000):
    """Fallback page fetcher, used only if a source's Tavily content is too
    short to extract meaningful findings from."""
    if not url:
        return ""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=10)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()
        text = " ".join(soup.get_text(separator=" ").split())
        return text[:max_chars]
    except Exception as e:
        print(f"[search_client] fetch failed for '{url}': {e}")
        return ""