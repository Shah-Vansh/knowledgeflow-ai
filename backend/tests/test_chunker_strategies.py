import re

import pytest

from app.rag.chunker import chunk_text


def test_fixed_size_short_text_single_chunk():
    text = "short text"
    chunks = chunk_text(text, strategy="fixed_size", chunk_size=500, overlap=0)
    assert chunks == [text]


def test_fixed_size_overlap_produces_overlapping_boundary():
    text = "0123456789" * 60  # 600 chars, no spaces so boundaries are exact
    chunks = chunk_text(text, strategy="fixed_size", chunk_size=200, overlap=50)
    assert len(chunks) >= 2
    assert chunks[1][:50] == chunks[0][-50:]


def test_fixed_size_empty_text():
    assert chunk_text("", strategy="fixed_size") == []


def test_recursive_prefers_paragraph_boundaries():
    text = (
        "Paragraph one is short.\n\n"
        "Paragraph two is also short.\n\n"
        "Paragraph three is short too."
    )
    chunks = chunk_text(text, strategy="recursive", chunk_size=1000, overlap=0)
    assert len(chunks) == 1
    assert "Paragraph one" in chunks[0]
    assert "Paragraph three" in chunks[0]


def test_recursive_splits_when_paragraphs_exceed_chunk_size():
    para_a = "A" * 100
    para_b = "B" * 100
    text = f"{para_a}\n\n{para_b}"
    chunks = chunk_text(text, strategy="recursive", chunk_size=120, overlap=0)
    assert len(chunks) == 2
    assert chunks[0].strip() == para_a
    assert chunks[1].strip() == para_b


def test_recursive_empty_text():
    assert chunk_text("", strategy="recursive") == []


def test_sentence_strategy_never_splits_mid_sentence():
    text = "This is sentence one. This is sentence two. This is sentence three."
    chunks = chunk_text(text, strategy="sentence", chunk_size=30, overlap=0)
    for chunk in chunks:
        assert re.search(r"[.!?]$", chunk.strip())


def test_sentence_strategy_empty_text():
    assert chunk_text("", strategy="sentence") == []


def test_unknown_strategy_raises():
    with pytest.raises(ValueError):
        chunk_text("some text", strategy="not_a_real_strategy")