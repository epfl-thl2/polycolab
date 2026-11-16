"""Bounded, text-only assistance with the platform-managed model."""

import json
from dataclasses import dataclass

from pydantic import SecretStr

from polycolab.model_gateway.responses import completed_response
from polycolab.model_gateway.transport import (
    ProviderTransport,
    ProviderTransportError,
    parse_base_url,
)

MAX_OUTPUT_TOKENS = 2048
SYSTEM_PROMPT = """You are Polycolab's research assistant. Help users develop research questions,
compare approaches, plan experiments, reason about evidence, and improve research writing.
Be clear about uncertainty and distinguish established findings from hypotheses.
Never invent citations, quotations, paper titles, or claims of having checked sources.
You have no web browsing, project files, private conversations, or platform action tools.
Ask users to provide the relevant material when needed. You cannot create projects or change files.
Use concise Markdown and ask focused questions when the research context is missing."""


@dataclass(frozen=True)
class ResearchProvider:
    base_url: str
    model: str
    wire_api: str
    api_key: SecretStr


def answer(
    provider: ResearchProvider,
    transport: ProviderTransport,
    messages: list[dict[str, str]],
) -> str:
    _, _, _, scheme = parse_base_url(provider.base_url)
    if scheme != "https":
        raise ProviderTransportError("unsafe_base_url")
    credential = provider.api_key.get_secret_value()
    try:
        if provider.wire_api == "responses":
            stream = transport.open_stream(
                base_url=provider.base_url,
                api_key=credential,
                responses=True,
                payload={
                    "model": provider.model,
                    "instructions": SYSTEM_PROMPT,
                    "input": messages,
                    "max_output_tokens": MAX_OUTPUT_TOKENS,
                    "stream": True,
                    "store": False,
                },
            )
            try:
                frames, _ = completed_response(
                    stream.chunks, max_bytes=262_144, max_output_tokens=MAX_OUTPUT_TOKENS
                )
            finally:
                stream.close()
            content = _response_text(frames)
        else:
            response = transport.request_json(
                base_url=provider.base_url,
                api_key=credential,
                payload={
                    "model": provider.model,
                    "messages": [{"role": "system", "content": SYSTEM_PROMPT}, *messages],
                    "max_tokens": MAX_OUTPUT_TOKENS,
                    "store": False,
                },
            )
            content = _chat_text(response)
    finally:
        credential = ""
    if not content.strip() or len(content) > 32_000:
        raise ProviderTransportError("provider_invalid_response")
    return content


def _response_text(frames: bytes) -> str:
    for event in frames.decode().replace("\r\n", "\n").split("\n\n"):
        lines = [line[5:].lstrip() for line in event.splitlines() if line.startswith("data:")]
        if not lines or lines == ["[DONE]"]:
            continue
        frame = json.loads("\n".join(lines))
        if frame.get("type") == "response.completed":
            try:
                return "\n".join(
                    part["text"]
                    for item in frame["response"]["output"]
                    if item["type"] == "message"
                    for part in item["content"]
                    if part["type"] == "output_text"
                )
            except KeyError, TypeError:
                raise ProviderTransportError("provider_invalid_response") from None
    raise ProviderTransportError("provider_invalid_response")


def _chat_text(response: dict[str, object]) -> str:
    choices = response.get("choices")
    if not isinstance(choices, list) or len(choices) != 1 or not isinstance(choices[0], dict):
        raise ProviderTransportError("provider_invalid_response")
    choice = choices[0]
    message = choice.get("message")
    if choice.get("finish_reason") != "stop" or not isinstance(message, dict):
        raise ProviderTransportError("provider_response_incomplete")
    content = message.get("content")
    if not isinstance(content, str) or not content.strip() or len(content) > 32_000:
        raise ProviderTransportError("provider_invalid_response")
    return content
