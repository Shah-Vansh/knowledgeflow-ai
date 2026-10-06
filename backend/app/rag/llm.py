from abc import ABC, abstractmethod

from groq import Groq

from app.core.config import settings


class LLMProvider(ABC):
    """
    Abstract interface for generating answers.
    Swapping providers should never require touching code outside this file.
    """

    @abstractmethod
    def generate(self, prompt: str) -> str:
        ...


class GroqLLMProvider(LLMProvider):
    def __init__(self):
        self._client = Groq(api_key=settings.GROQ_API_KEY)
        self._model = settings.GROQ_LLM_MODEL

    def generate(self, prompt: str) -> str:
        response = self._client.chat.completions.create(
            model=self._model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
        )
        return response.choices[0].message.content.strip()


def get_llm_provider() -> LLMProvider:
    return GroqLLMProvider()