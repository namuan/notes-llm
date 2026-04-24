from __future__ import annotations

from pathlib import Path
import json

from html_converter import html_to_plaintext

try:
    import fitz
except ImportError:  # pragma: no cover - optional dependency
    fitz = None


def extract_pdf_text(filepath: str | Path) -> str:
    if fitz is None:
        raise RuntimeError("PyMuPDF is required for PDF extraction")

    path = Path(filepath)
    with fitz.open(path) as document:
        return "\n\n".join(page.get_text("text") for page in document)


def extract_html_text(filepath: str | Path) -> str:
    return html_to_plaintext(
        Path(filepath).read_text(encoding="utf-8", errors="ignore")
    )


def extract_content(filepath: str | Path) -> str:
    path = Path(filepath)
    suffix = path.suffix.lower()
    if suffix in {".md", ".txt", ".csv"}:
        return path.read_text(encoding="utf-8", errors="ignore")
    if suffix == ".json":
        payload = json.loads(path.read_text(encoding="utf-8", errors="ignore"))
        return json.dumps(payload, indent=2, sort_keys=True)
    if suffix == ".pdf":
        return extract_pdf_text(path)
    if suffix == ".html":
        return extract_html_text(path)
    raise ValueError(f"Unsupported file type: {suffix}")
