from tools.support_tools import html_to_text, parse_page_urls, select_relevant


def test_parse_page_urls_labels_and_bare_urls():
    pages = parse_page_urls("terms=https://s.com/terms, https://s.com/privacy ,")
    assert pages == {"terms": "https://s.com/terms", "privacy": "https://s.com/privacy"}


def test_html_to_text_drops_chrome():
    html = "<nav>Menu</nav><h1>Terms</h1><p>No returns on <b>food</b>.</p><script>x()</script><footer>(c)</footer>"
    assert html_to_text(html) == "Terms\nNo returns on food."


def test_select_relevant_keeps_matching_paragraphs():
    text = "\n".join(["intro filler " * 20, "Refund within 7 days of delivery", "other filler " * 20])
    out = select_relevant(text, "refund days", 60)
    assert "Refund within 7 days" in out and "filler" not in out


def test_select_relevant_short_text_untouched():
    assert select_relevant("short", "x", 100) == "short"
