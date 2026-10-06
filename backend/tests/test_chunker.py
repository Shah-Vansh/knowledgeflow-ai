from app.rag.chunker import chunk_text


def test_chunk_text_splits_long_text():
    text = "word " * 300  # ~1500 chars
    chunks = chunk_text(text, chunk_size=500)
    assert len(chunks) > 1
    assert all(len(c) <= 520 for c in chunks)


def test_chunk_text_empty_input():
    assert chunk_text("", chunk_size=500) == []


def test_chunk_text_short_input_single_chunk():
    text = "short text"
    chunks = chunk_text(text, chunk_size=500)
    assert len(chunks) == 1
    assert chunks[0] == text