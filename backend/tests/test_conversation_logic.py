import pytest

from app.rag.conversation import (
    MAX_HISTORY_CHARS,
    MAX_HISTORY_MESSAGES,
    build_history_text,
    clean_standalone,
    contextualize_question,
)
from app.rag.llm import LLMProvider


class FakeLLM(LLMProvider):
    """Plays back a script: each call returns the next string, or raises the next Exception."""

    def __init__(self, script):
        self.script = list(script)
        self.calls = []
        self.temperatures = []

    def generate(self, prompt, temperature=0.2):
        self.calls.append(prompt)
        self.temperatures.append(temperature)
        if not self.script:
            raise AssertionError("unexpected extra LLM call")
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


HISTORY = [
    {"role": "user", "content": "Explain transformers."},
    {"role": "assistant", "content": "Transformers are neural networks that process sequences in parallel."},
]


def test_no_history_makes_no_llm_call():
    llm = FakeLLM([])
    result = contextualize_question(llm, [], "Explain transformers.")

    assert result.standalone == "Explain transformers."
    assert result.rewritten is False
    assert result.fallback_used is False
    assert llm.calls == []


def test_followup_is_rewritten_using_history():
    llm = FakeLLM(["What is the main advantage of transformers?"])
    result = contextualize_question(llm, HISTORY, "What is their main advantage?")

    assert result.standalone == "What is the main advantage of transformers?"
    assert result.rewritten is True
    assert len(llm.calls) == 1
    assert llm.temperatures == [0.0]
    assert "Explain transformers." in llm.calls[0]
    assert "process sequences in parallel" in llm.calls[0]
    assert "What is their main advantage?" in llm.calls[0]


def test_unchanged_question_is_not_marked_rewritten():
    llm = FakeLLM(["what is the main advantage of transformers"])
    result = contextualize_question(llm, HISTORY, "What is the main advantage of transformers?")
    assert result.rewritten is False


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("What is X?", "What is X?"),
        ('"What is X?"', "What is X?"),
        ("Standalone question: What is X?", "What is X?"),
        ('"Standalone question: What is X?"', "What is X?"),
        ("Here is the rewritten question:\nWhat is X?", "What is X?"),
        ("What is X?\n\nI rewrote it by replacing 'it'.", "What is X?"),
        ("   What   is   X?   ", "What is X?"),
    ],
)
def test_clean_standalone_accepts(raw, expected):
    assert clean_standalone(raw) == expected


@pytest.mark.parametrize("raw", ["", "   ", "???", "a" * 401, None, 42])
def test_clean_standalone_rejects(raw):
    assert clean_standalone(raw) is None


def test_llm_error_falls_back_to_original():
    llm = FakeLLM([RuntimeError("boom")])
    result = contextualize_question(llm, HISTORY, "What is their main advantage?")

    assert result.fallback_used is True
    assert result.rewritten is False
    assert result.standalone == "What is their main advantage?"
    assert "boom" in result.error


def test_unusable_output_falls_back_to_original():
    llm = FakeLLM([""])
    result = contextualize_question(llm, HISTORY, "What is their main advantage?")

    assert result.fallback_used is True
    assert result.standalone == "What is their main advantage?"


def test_history_text_keeps_only_recent_messages_and_truncates():
    history = [
        {"role": "user" if i % 2 == 0 else "assistant", "content": f"message {i} " + "x" * 2000}
        for i in range(10)
    ]
    text = build_history_text(history)
    lines = text.splitlines()

    assert len(lines) == MAX_HISTORY_MESSAGES
    assert lines[0].startswith("User: message 4 ")       # oldest kept message is #4 of 0..9
    assert lines[1].startswith("Assistant: message 5 ")
    assert all(len(line) <= MAX_HISTORY_CHARS + len("Assistant: ") + 1 for line in lines)
    assert "message 3" not in text


def test_history_text_collapses_whitespace():
    text = build_history_text([{"role": "user", "content": "line one\n\n   line   two"}])
    assert text == "User: line one line two"