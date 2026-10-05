"""Strands tools for the SupportAgent: website policy pages + knowledge base.

Three read-only sources, in order of preference:

1. ``support_read_website_page`` — live text of the store's own Terms &
   Conditions / policy pages. Only URLs configured in ``SUPPORT_PAGE_URLS``
   can be fetched (allow-list), so the model can never be steered to an
   arbitrary host.
2. ``support_search_knowledge_base`` — Bedrock Knowledge Base passages (FAQ).
3. ``support_get_faq`` — the bundled ``sops/faq.md``, used when the KB is not
   configured or is unreachable.
"""

import re
import time
from html.parser import HTMLParser
from typing import Any, Dict, List, Optional

import httpx
from strands import tool

from configs.settings import settings
from services.knowledge_base_service import KnowledgeBaseService
from tools.ecommerce_tools import ToolBundle
from utils.common import CommonUtility
from utils.logger import Logger

_SKIP_TAGS = {"script", "style", "noscript", "nav", "footer", "header", "svg", "form"}
_BLOCK_TAGS = {"p", "div", "li", "br", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "section"}


class _TextExtractor(HTMLParser):
    """Minimal HTML → readable text; drops chrome (nav/footer/scripts)."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self._skip = 0
        self._parts: List[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in _SKIP_TAGS:
            self._skip += 1
        elif tag in _BLOCK_TAGS:
            self._parts.append("\n")

    def handle_endtag(self, tag):
        if tag in _SKIP_TAGS and self._skip:
            self._skip -= 1
        elif tag in _BLOCK_TAGS:
            self._parts.append("\n")

    def handle_data(self, data):
        if not self._skip:
            self._parts.append(data)

    def text(self) -> str:
        raw = "".join(self._parts)
        lines = (re.sub(r"[ \t]+", " ", ln).strip() for ln in raw.splitlines())
        return "\n".join(ln for ln in lines if ln)


def html_to_text(html: str) -> str:
    parser = _TextExtractor()
    parser.feed(html)
    return parser.text()


def parse_page_urls(raw: str) -> Dict[str, str]:
    """``"terms=https://a/t,privacy=https://a/p"`` → ``{"terms": url, ...}``.
    An entry without ``label=`` is labelled by its URL path's last segment."""
    pages: Dict[str, str] = {}
    for entry in (raw or "").split(","):
        entry = entry.strip()
        if not entry:
            continue
        if "=" in entry and not entry.lower().startswith("http"):
            label, url = entry.split("=", 1)
        else:
            url = entry
            label = url.rstrip("/").rsplit("/", 1)[-1] or url
        pages[label.strip().lower()] = url.strip()
    return pages


def select_relevant(text: str, query: str, max_chars: int) -> str:
    """Trim ``text`` to ``max_chars``, keeping the paragraphs that best match
    ``query`` (by shared words) in original order. Short text is returned as-is."""
    if len(text) <= max_chars:
        return text
    words = {w for w in re.findall(r"[a-z0-9]{3,}", (query or "").lower())}
    paragraphs = text.split("\n")
    scored = sorted(
        range(len(paragraphs)),
        key=lambda i: -sum(w in paragraphs[i].lower() for w in words),
    )
    keep, used = set(), 0
    for i in scored:
        if used + len(paragraphs[i]) > max_chars:
            continue
        keep.add(i)
        used += len(paragraphs[i]) + 1
    return "\n".join(paragraphs[i] for i in sorted(keep))


class SupportTools:
    def __init__(self, logger_config):
        self.logger = Logger(__name__, logger_config)
        self.pages = parse_page_urls(settings.support_page_urls)
        self.kb = KnowledgeBaseService(logger_config)
        self._faq = CommonUtility(logger_config).load_faq("faq.md")
        self._cache: Dict[str, tuple[float, str]] = {}

    def _fetch(self, url: str) -> str:
        cached = self._cache.get(url)
        if cached and time.monotonic() - cached[0] < settings.support_page_cache_ttl:
            return cached[1]
        resp = httpx.get(
            url,
            timeout=settings.support_page_timeout,
            follow_redirects=True,
            headers={"User-Agent": f"{settings.brand_name}-support-bot"},
        )
        resp.raise_for_status()
        text = html_to_text(resp.text)
        self._cache[url] = (time.monotonic(), text)
        return text

    @tool(name="support_list_pages")
    def list_pages(self) -> Any:
        """List the store's policy pages that can be read (e.g. terms, privacy,
        returns). Use the returned ``label`` with ``support_read_website_page``."""
        return {"pages": [{"label": k, "url": v} for k, v in self.pages.items()]}

    @tool(name="support_read_website_page")
    def read_page(self, page: str, query: str = "") -> Any:
        """Read a live policy page from the store's website.

        Args:
            page: a label from ``support_list_pages`` (e.g. "terms").
            query: the user's question; long pages are trimmed to the sections
                that best match it.
        """
        url = self.pages.get((page or "").strip().lower())
        if not url:
            return {"status": "UNKNOWN_PAGE", "available": list(self.pages)}
        try:
            text = self._fetch(url)
        except Exception as exc:  # noqa: BLE001
            self.logger.exception(f"[support] page fetch failed {url}: {exc}")
            return {"status": "ERROR", "message": "Could not load the page."}
        return {
            "status": "OK",
            "source": url,
            "text": select_relevant(text, query, settings.support_page_max_chars),
        }

    @tool(name="support_search_knowledge_base")
    def search_kb(self, question: str) -> Any:
        """Search the FAQ knowledge base. Returns passages with their sources."""
        if not self.kb.enabled:
            return {"status": "DISABLED"}
        try:
            passages = self.kb.retrieve(question)
        except Exception as exc:  # noqa: BLE001
            self.logger.exception(f"[support] KB retrieval failed: {exc}")
            return {"status": "ERROR"}
        if not passages:
            return {"status": "NO_MATCH"}
        return {"status": "OK", "passages": passages}

    @tool(name="support_get_faq")
    def get_faq(self) -> Any:
        """Return the bundled store FAQ. Use when the knowledge base is
        unavailable or returned nothing."""
        return {"status": "OK" if self._faq else "EMPTY", "faq": self._faq}


def support_tools(logger_config) -> ToolBundle:
    st = SupportTools(logger_config)
    return ToolBundle(
        [st],
        [st.list_pages, st.read_page, st.search_kb, st.get_faq],
    )
