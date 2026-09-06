"""
A tiny HTML-to-text converter built on the standard library's html.parser.

It keeps just enough structure for the chunker: headings become markdown
headings ("## Title"), block elements become paragraph breaks, and
scripts/styles are dropped. No third-party HTML library is needed for this.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser

BLOCK_TAGS = {
    "p", "div", "section", "article", "header", "footer", "main", "aside", "nav", "blockquote", "pre",
    "ul", "ol", "li", "table", "thead", "tbody", "tr", "dl", "dt", "dd", "hr", "figure", "figcaption",
    "br", "form", "fieldset", "address",
}  # fmt: skip
HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
SKIP_TAGS = {"script", "style", "noscript", "template", "head", "svg"}


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip_depth = 0
        self._heading: str | None = None  # the "#..." prefix while inside an <hN>

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in SKIP_TAGS:
            self._skip_depth += 1
        elif tag in HEADING_TAGS:
            self.parts.append("\n\n" + "#" * int(tag[1]) + " ")
            self._heading = tag
        elif tag in BLOCK_TAGS:
            self.parts.append("\n\n" if tag != "br" else "\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in SKIP_TAGS:
            self._skip_depth = max(0, self._skip_depth - 1)
        elif tag in HEADING_TAGS:
            self.parts.append("\n\n")
            self._heading = None
        elif tag in BLOCK_TAGS:
            self.parts.append("\n\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        # Inside a heading, collapse whitespace so the heading stays on one line.
        self.parts.append(re.sub(r"\s+", " ", data) if self._heading else data)


def html_to_text(html: str) -> str:
    """Strip tags, keep paragraph breaks and headings. Returns clean text with at most one blank line between blocks."""
    parser = _TextExtractor()
    parser.feed(html)
    parser.close()
    text = "".join(parser.parts)
    # Tidy: strip trailing spaces per line, collapse runs of blank lines, drop empty headings.
    lines = [line.strip() for line in text.splitlines()]
    lines = [line for line in lines if not re.fullmatch(r"#+", line)]
    text = "\n".join(lines)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()
