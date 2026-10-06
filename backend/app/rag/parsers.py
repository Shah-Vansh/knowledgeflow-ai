from typing import List, Optional, Tuple

import fitz  # PyMuPDF


def extract_text_from_pdf(file_path: str) -> str:
    text_parts = []
    with fitz.open(file_path) as doc:
        for page in doc:
            text_parts.append(page.get_text())
    return "\n".join(text_parts).strip()


def extract_text_from_txt(file_path: str) -> str:
    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
        return f.read().strip()


def extract_text(file_path: str, filename: str) -> str:
    if "." not in filename:
        raise ValueError(f"Cannot determine file type for: {filename}")

    ext = filename.lower().rsplit(".", 1)[-1]

    if ext == "pdf":
        return extract_text_from_pdf(file_path)
    elif ext == "txt":
        return extract_text_from_txt(file_path)
    else:
        raise ValueError(f"Unsupported file type: {ext}")


def extract_pages_from_pdf(file_path: str) -> List[Tuple[int, str]]:
    """Returns [(page_number, page_text), ...], 1-indexed, skipping blank pages."""
    pages: List[Tuple[int, str]] = []
    with fitz.open(file_path) as doc:
        for i, page in enumerate(doc, start=1):
            text = page.get_text().strip()
            if text:
                pages.append((i, text))
    return pages


def extract_pages(file_path: str, filename: str) -> List[Tuple[Optional[int], str]]:
    """
    Page-aware extraction. PDFs return real page numbers; TXT files have no
    concept of pages, so they return a single (None, text) entry.
    """
    if "." not in filename:
        raise ValueError(f"Cannot determine file type for: {filename}")

    ext = filename.lower().rsplit(".", 1)[-1]

    if ext == "pdf":
        return extract_pages_from_pdf(file_path)
    elif ext == "txt":
        text = extract_text_from_txt(file_path)
        return [(None, text)] if text else []
    else:
        raise ValueError(f"Unsupported file type: {ext}")