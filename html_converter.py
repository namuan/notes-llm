from __future__ import annotations

from html import unescape
from html.parser import HTMLParser
import re

try:
    import markdown as markdown_lib
except ImportError:  # pragma: no cover - optional dependency
    markdown_lib = None

try:
    from bs4 import BeautifulSoup
except ImportError:  # pragma: no cover - optional dependency
    BeautifulSoup = None


SUPPORTED_TAGS = {
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "b",
    "strong",
    "i",
    "em",
    "u",
    "ul",
    "ol",
    "li",
    "br",
    "div",
    "p",
    "a",
    "font",
}


def _fallback_markdown_to_html(md_text: str) -> str:
    lines = md_text.splitlines()
    html_lines: list[str] = []
    in_list = False
    for raw_line in lines:
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped:
            if in_list:
                html_lines.append("</ul>")
                in_list = False
            continue
        if stripped.startswith("#"):
            if in_list:
                html_lines.append("</ul>")
                in_list = False
            level = min(len(stripped) - len(stripped.lstrip("#")), 6)
            content = stripped[level:].strip()
            html_lines.append(f"<h{level}>{_inline_markdown(content)}</h{level}>")
            continue
        if stripped.startswith(("- ", "* ")):
            if not in_list:
                html_lines.append("<ul>")
                in_list = True
            html_lines.append(f"<li>{_inline_markdown(stripped[2:].strip())}</li>")
            continue
        if in_list:
            html_lines.append("</ul>")
            in_list = False
        html_lines.append(f"<p>{_inline_markdown(stripped)}</p>")
    if in_list:
        html_lines.append("</ul>")
    return "\n".join(html_lines)


def _inline_markdown(text: str) -> str:
    escaped = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    escaped = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", escaped)
    escaped = re.sub(r"\*(.+?)\*", r"<i>\1</i>", escaped)
    return escaped


def _sanitize_html(html_body: str) -> str:
    if BeautifulSoup is None:
        html_body = re.sub(
            r"<\/?(table|thead|tbody|tr|td|th)[^>]*>",
            "",
            html_body,
            flags=re.IGNORECASE,
        )
        html_body = re.sub(r"<img[^>]*>", "", html_body, flags=re.IGNORECASE)
        html_body = re.sub(r"<\/?(pre|code)[^>]*>", "", html_body, flags=re.IGNORECASE)
        html_body = re.sub(r"\sstyle=\"[^\"]*\"", "", html_body)
        return html_body

    soup = BeautifulSoup(html_body, "html.parser")
    for tag in list(soup.find_all(True)):
        if tag.name in {"img", "table", "thead", "tbody", "tr", "td", "th"}:
            tag.decompose()
            continue
        if tag.name in {"pre", "code"}:
            tag.unwrap()
            continue
        if tag.name not in SUPPORTED_TAGS:
            tag.unwrap()
            continue
        if tag.attrs:
            allowed = {}
            if tag.name == "a" and "href" in tag.attrs:
                allowed["href"] = tag.attrs["href"]
            if tag.name == "font":
                for key in ("color", "face"):
                    if key in tag.attrs:
                        allowed[key] = tag.attrs[key]
            tag.attrs = allowed
    return str(soup)


def md_to_apple_notes_html(md_text: str) -> str:
    if markdown_lib is not None:
        rendered = markdown_lib.markdown(
            md_text, extensions=["tables", "fenced_code", "nl2br"]
        )
    else:
        rendered = _fallback_markdown_to_html(md_text)
    return _sanitize_html(rendered)


class _PlainTextHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self._list_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"br"}:
            self.parts.append("\n")
        elif tag in {"p", "div"}:
            self.parts.append("\n")
        elif tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            self.parts.append("\n# ")
        elif tag in {"ul", "ol"}:
            self._list_depth += 1
            self.parts.append("\n")
        elif tag == "li":
            indent = "  " * max(self._list_depth - 1, 0)
            self.parts.append(f"\n{indent}- ")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"p", "div", "h1", "h2", "h3", "h4", "h5", "h6"}:
            self.parts.append("\n")
        elif tag in {"ul", "ol"} and self._list_depth > 0:
            self._list_depth -= 1
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        self.parts.append(data)

    def get_text(self) -> str:
        text = unescape("".join(self.parts))
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()


def html_to_plaintext(html_body: str) -> str:
    parser = _PlainTextHTMLParser()
    parser.feed(html_body)
    parser.close()
    return parser.get_text()
