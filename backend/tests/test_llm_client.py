"""LiteLLMClient perf 옵션 테스트 — 프롬프트 캐싱 주입 + 스트리밍 재조립(dev 러너 속도).

캐싱: system + 마지막 문자열 content 메시지에 cache_control(ephemeral). tool_call(content=None)은
불변. 스트리밍: completion(stream=True) 청크 → stream_chunk_builder 재조립 → 파싱 동일.
"""

from __future__ import annotations

import json
import types

from app.services.orchestrator import LiteLLMClient, _inject_cache_control


def test_inject_cache_control_system_and_last():
    msgs = [
        {"role": "system", "content": "you are a dev"},
        {"role": "user", "content": "build X"},
        {"role": "assistant", "content": None, "tool_calls": [{"id": "c1"}]},
        {"role": "tool", "tool_call_id": "c1", "content": "exit 0"},
    ]
    out = _inject_cache_control(msgs)
    # 원본 불변(복사본 반환).
    assert msgs[0]["content"] == "you are a dev"
    # system 블록화 + cache_control.
    assert out[0]["content"][0]["cache_control"] == {"type": "ephemeral"}
    assert out[0]["content"][0]["text"] == "you are a dev"
    # rolling = 마지막 문자열 content(tool 메시지)에 붙음.
    assert out[3]["content"][0]["cache_control"] == {"type": "ephemeral"}
    assert out[3]["content"][0]["text"] == "exit 0"
    # content=None assistant는 불변.
    assert out[2]["content"] is None
    # user는 마지막이 아니므로 문자열 그대로(단일 rolling breakpoint).
    assert out[1]["content"] == "build X"


def test_complete_non_stream_parses_tool_calls(monkeypatch):
    client = LiteLLMClient.__new__(LiteLLMClient)
    client.model, client.stream, client.cache = "claude-x", False, True
    captured = {}

    def fake_completion(**kwargs):
        captured.update(kwargs)
        tc = types.SimpleNamespace(id="t1", function=types.SimpleNamespace(name="bash", arguments='{"cmd":"ls"}'))
        msg = types.SimpleNamespace(tool_calls=[tc], content=None)
        return types.SimpleNamespace(choices=[types.SimpleNamespace(message=msg)])

    monkeypatch.setattr("litellm.completion", fake_completion)
    resp = client.complete([{"role": "system", "content": "s"}, {"role": "user", "content": "go"}], [])
    assert resp.tool_calls[0].name == "bash" and resp.tool_calls[0].args == {"cmd": "ls"}
    # cache=True → messages에 cache_control 주입되어 전달됨.
    assert captured["messages"][0]["content"][0]["cache_control"] == {"type": "ephemeral"}
    assert "stream" not in captured  # 비스트리밍 경로


def test_complete_stream_reassembles(monkeypatch):
    client = LiteLLMClient.__new__(LiteLLMClient)
    client.model, client.stream, client.cache = "claude-x", True, False
    seen = {}

    def fake_completion(**kwargs):
        seen["stream"] = kwargs.get("stream")
        return iter([f"chunk{i}" for i in range(3)])  # 청크 스트림 흉내

    def fake_builder(chunks, messages=None):
        seen["chunks"] = list(chunks)
        msg = types.SimpleNamespace(tool_calls=None, content="final answer")
        return types.SimpleNamespace(choices=[types.SimpleNamespace(message=msg)])

    monkeypatch.setattr("litellm.completion", fake_completion)
    monkeypatch.setattr("litellm.stream_chunk_builder", fake_builder)
    resp = client.complete([{"role": "user", "content": "hi"}], [])
    assert resp.content == "final answer"
    assert seen["stream"] is True and seen["chunks"] == ["chunk0", "chunk1", "chunk2"]
