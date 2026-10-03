"""Teaching JSON quotes remain opaque to the Chat think-tag parser."""
import json

import httpx
import pytest

from app import teaching_runtime as teaching
from app.function_tools import ToolSession, ToolTurn
from app.providers import ProviderChunk, ProviderConfig, build_provider


def event(body):
    return "data: " + json.dumps(body, ensure_ascii=False) + "\n\n"


def provider_for(raw, chunk_size):
    wire = "".join(event({"choices": [{"delta": {"content": raw[index:index + chunk_size]}}]})
                   for index in range(0, len(raw), chunk_size))
    wire += event({"choices": [{"delta": {}, "finish_reason": "stop"}]}) + "data: [DONE]\n\n"
    return build_provider(ProviderConfig(base_url="https://provider.example.test/v1", model="fixture-model",
                                        api_key="fixture-key"),
                          httpx.MockTransport(lambda _: httpx.Response(200, text=wire)))


async def stream_for(provider, messages, tool_session):
    if not tool_session:
        async for chunk in provider.stream_chat(messages):
            yield chunk
        return
    async for chunk in ToolSession(provider, messages).stream_turn([]):
        if isinstance(chunk, ToolTurn):
            yield ProviderChunk("turn_end", "")
            yield ProviderChunk("completion", chunk.completion)
        else:
            yield chunk


@pytest.mark.asyncio
@pytest.mark.parametrize("tool_session", [False, True])
@pytest.mark.parametrize("chunk_size", [1, 7, 4096])
@pytest.mark.parametrize("quote", [
    "我得到 <think>x</think> 这个结果",
    "我写了 <think> 标签",
    "我写了 </think> 标签",
])
async def test_literal_think_tags_in_attempt_keep_exact_quote_and_hide_trailer(tool_session, chunk_size, quote):
    frozen = teaching.freeze([], answer_id="answer-fixture", message_id="user-fixture",
                             kind="conversation", scope_id="scope-fixture")
    frozen["before"]["step"] = {"id": "prior-fixture", "source_answer_id": "prior-fixture",
                                "text": "检查输入边界"}
    opening, closing = teaching.markers(frozen)
    proposal = {"step": None, "attempt": {"quote": quote}, "mode": None}
    body = "回应本轮尝试。\n"
    raw = "<think>合成推理</think>" + body + opening + json.dumps(proposal, ensure_ascii=False) + closing
    messages = teaching.add_prompt([{"role": "system", "content": "合成系统"},
                                    {"role": "user", "content": quote}], frozen)
    parser = teaching.TeachingStream(frozen)
    chunks = [chunk async for chunk in parser.filter(stream_for(provider_for(raw, chunk_size), messages, tool_session))]

    assert "".join(chunk.text for chunk in chunks if chunk.kind == "content") == body
    assert "".join(chunk.text for chunk in chunks if chunk.kind == "reasoning") == "合成推理"
    assert not any("nautilus_teaching_" in chunk.text for chunk in chunks)
    assert parser.proposal() == proposal
    result = teaching.complete(frozen, parser.proposal(), body=body, user_text=quote, at="fixture")
    assert result is not None
    assert quote[result["attempt"]["start"]:result["attempt"]["end"]] == quote


@pytest.mark.asyncio
@pytest.mark.parametrize("tool_session", [False, True])
async def test_without_current_teaching_context_preserves_existing_think_behavior(tool_session):
    messages = [{"role": "user", "content": "合成问题"}]
    chunks = [chunk async for chunk in stream_for(provider_for("<think>合成推理</think>合成正文", 1), messages, tool_session)]
    assert "".join(chunk.text for chunk in chunks if chunk.kind == "reasoning") == "合成推理"
    assert "".join(chunk.text for chunk in chunks if chunk.kind == "content") == "合成正文"
