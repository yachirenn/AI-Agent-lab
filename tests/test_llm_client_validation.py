import json

import httpx
import pytest

from app.agent.llm_client import GeminiClient, LLMError, OpenAICompatClient


def _client_with_response(client, payload):
    def handler(request):
        return httpx.Response(200, json=payload)

    client._http.close()
    client._http = httpx.Client(
        transport=httpx.MockTransport(handler),
        timeout=1.0,
    )
    return client


@pytest.mark.parametrize("args", [
    [],
    "halo",
    123,
])
def test_openai_rejects_tool_arguments_that_are_not_objects(args):
    client = OpenAICompatClient(
        name="test",
        base_url="https://example.invalid/v1",
        api_key="test-key",
        model="test-model",
    )
    payload = {
        "choices": [{
            "message": {
                "content": "",
                "tool_calls": [{
                    "id": "call_1",
                    "type": "function",
                    "function": {
                        "name": "search_faq",
                        "arguments": json.dumps(args),
                    },
                }],
            }
        }]
    }
    _client_with_response(client, payload)

    with pytest.raises(LLMError):
        client.chat("system", [{"role": "user", "text": "halo"}], [])


@pytest.mark.parametrize("args", [
    [],
    "halo",
    123,
])
def test_gemini_rejects_tool_arguments_that_are_not_objects(args):
    client = GeminiClient(api_key="test-key", model="test-model")
    payload = {
        "candidates": [{
            "content": {
                "parts": [{
                    "functionCall": {
                        "name": "search_faq",
                        "args": args,
                    }
                }]
            }
        }]
    }
    _client_with_response(client, payload)

    with pytest.raises(LLMError):
        client.chat("system", [{"role": "user", "text": "halo"}], [])

