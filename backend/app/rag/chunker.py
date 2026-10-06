import re
from typing import List


def _chunk_fixed_size(text: str, chunk_size: int = 500, overlap: int = 0) -> List[str]:
    text = text.strip()
    if not text:
        return []

    if overlap >= chunk_size:
        raise ValueError("overlap must be smaller than chunk_size")

    chunks: List[str] = []
    start = 0
    length = len(text)

    while start < length:
        end = start + chunk_size

        if end >= length:
            piece = text[start:length].strip()
            if piece:
                chunks.append(piece)
            break

        boundary = text.rfind(" ", start, end)
        if boundary == -1 or boundary <= start:
            boundary = end

        piece = text[start:boundary].strip()
        if piece:
            chunks.append(piece)

        next_start = boundary - overlap
        if next_start <= start:
            next_start = boundary
        start = next_start

    return chunks


def _split_paragraphs(text: str) -> List[str]:
    return [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]


def _split_sentences(text: str) -> List[str]:
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    return [s.strip() for s in sentences if s.strip()]


def _chunk_recursive(text: str, chunk_size: int = 500, overlap: int = 0) -> List[str]:
    """
    Tries the largest natural boundary first (paragraphs), falls back to
    sentences, then to raw fixed-size splitting only if a single sentence
    is still too long.
    """
    text = text.strip()
    if not text:
        return []

    paragraphs = _split_paragraphs(text) or [text]
    chunks: List[str] = []
    buffer = ""

    def flush():
        nonlocal buffer
        if buffer.strip():
            chunks.append(buffer.strip())
        buffer = ""

    for para in paragraphs:
        if len(para) > chunk_size:
            flush()
            sentences = _split_sentences(para)
            sbuffer = ""
            for sentence in sentences:
                if len(sbuffer) + len(sentence) + 1 <= chunk_size:
                    sbuffer = (sbuffer + " " + sentence).strip() if sbuffer else sentence
                else:
                    if sbuffer:
                        chunks.append(sbuffer)
                    if len(sentence) > chunk_size:
                        chunks.extend(_chunk_fixed_size(sentence, chunk_size=chunk_size, overlap=0))
                        sbuffer = ""
                    else:
                        sbuffer = sentence
            if sbuffer:
                chunks.append(sbuffer)
        else:
            if len(buffer) + len(para) + 2 <= chunk_size:
                buffer = (buffer + "\n\n" + para).strip() if buffer else para
            else:
                flush()
                buffer = para

    flush()
    return chunks


def _chunk_sentence(text: str, chunk_size: int = 500, overlap: int = 0) -> List[str]:
    text = text.strip()
    if not text:
        return []

    sentences = _split_sentences(text)
    if not sentences:
        return []

    chunks: List[str] = []
    buffer = ""

    for sentence in sentences:
        if len(buffer) + len(sentence) + 1 <= chunk_size:
            buffer = (buffer + " " + sentence).strip() if buffer else sentence
        else:
            if buffer:
                chunks.append(buffer)
            if len(sentence) > chunk_size:
                chunks.extend(_chunk_fixed_size(sentence, chunk_size=chunk_size, overlap=0))
                buffer = ""
            else:
                buffer = sentence

    if buffer:
        chunks.append(buffer)

    return chunks


def chunk_text(text: str, strategy: str = "fixed_size", chunk_size: int = 500, overlap: int = 0) -> List[str]:
    """
    Dispatches to one of three chunking strategies:
      - fixed_size: naive character-based splitting, word-boundary aware, optional overlap
      - recursive: prefers paragraph boundaries, falls back to sentences, falls back to fixed_size
      - sentence: never splits mid-sentence

    Defaults (fixed_size, 500, 0) match Phase 1 behavior exactly when no
    parameters are supplied, so existing calls remain unaffected.
    """
    if strategy == "fixed_size":
        return _chunk_fixed_size(text, chunk_size=chunk_size, overlap=overlap)
    elif strategy == "recursive":
        return _chunk_recursive(text, chunk_size=chunk_size, overlap=overlap)
    elif strategy == "sentence":
        return _chunk_sentence(text, chunk_size=chunk_size, overlap=overlap)
    else:
        raise ValueError(f"Unknown chunking strategy: {strategy}")