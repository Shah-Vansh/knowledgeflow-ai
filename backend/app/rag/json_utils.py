import json
import re
from typing import Any


def extract_json_object(raw: Any) -> dict:
    """
    Pulls one JSON object out of model output. Tolerates markdown code fences and
    text around the object. Raises ValueError when there is no usable object.
    """
    if not isinstance(raw, str):
        raise ValueError("model returned no text")

    text = raw.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text)

    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("no JSON object found in model output")

    try:
        data = json.loads(text[start:end + 1])
    except json.JSONDecodeError as exc:
        raise ValueError(f"model output is not valid JSON: {exc}") from exc

    if not isinstance(data, dict):
        raise ValueError("model output JSON is not an object")
    return data