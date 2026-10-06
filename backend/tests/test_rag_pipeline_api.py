import io
import os

import pytest

pytestmark = pytest.mark.skipif(
    not os.getenv("OPENAI_API_KEY"),
    reason="Requires a real OPENAI_API_KEY and will call the OpenAI API (costs apply).",
)


def test_upload_and_query_txt_document(client):
    content = b"The capital of France is Paris. It is known for the Eiffel Tower."
    files = {"file": ("sample.txt", io.BytesIO(content), "text/plain")}

    upload_response = client.post("/documents/upload", files=files)
    assert upload_response.status_code == 200
    body = upload_response.json()
    assert body["status"] == "processed"

    query_response = client.post("/query", json={"question": "What is the capital of France?"})
    assert query_response.status_code == 200
    answer = query_response.json()["answer"]
    assert "Paris" in answer