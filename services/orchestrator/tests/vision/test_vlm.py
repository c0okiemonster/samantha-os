from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from integrations.vision.vlm import describe, VISION_PROMPT


async def _mock_httpx_response(json_body):
    resp = MagicMock()
    resp.status_code = 200
    resp.json = MagicMock(return_value=json_body)
    resp.raise_for_status = MagicMock()
    return resp


async def test_describe_happy_path():
    """Returns the 'response' field from Ollama generate API."""
    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.post = AsyncMock(return_value=await _mock_httpx_response(
        {"response": "A wooden desk with a cup of coffee and a potted plant."}
    ))

    with patch("integrations.vision.vlm.httpx.AsyncClient", return_value=mock_client):
        result = await describe(
            image_b64="fakebase64",
            model="moondream",
            host="host.docker.internal:11434",
            timeout_s=5.0,
        )

    assert result == "A wooden desk with a cup of coffee and a potted plant."
    # Verify request shape
    call_args = mock_client.post.call_args
    url = call_args[0][0]
    assert url == "http://host.docker.internal:11434/api/generate"
    payload = call_args[1]["json"]
    assert payload["model"] == "moondream"
    assert payload["stream"] is False
    assert payload["images"] == ["fakebase64"]
    assert VISION_PROMPT in payload["prompt"]


async def test_describe_http_error_returns_empty():
    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.post = AsyncMock(side_effect=Exception("connection refused"))

    with patch("integrations.vision.vlm.httpx.AsyncClient", return_value=mock_client):
        result = await describe("b64", "moondream", "localhost:11434", 5.0)

    assert result == ""


async def test_describe_empty_response_returns_empty():
    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.post = AsyncMock(return_value=await _mock_httpx_response(
        {"response": "   "}
    ))

    with patch("integrations.vision.vlm.httpx.AsyncClient", return_value=mock_client):
        result = await describe("b64", "moondream", "localhost:11434", 5.0)

    assert result == ""


async def test_describe_missing_response_field_returns_empty():
    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.post = AsyncMock(return_value=await _mock_httpx_response({}))

    with patch("integrations.vision.vlm.httpx.AsyncClient", return_value=mock_client):
        result = await describe("b64", "moondream", "localhost:11434", 5.0)

    assert result == ""
