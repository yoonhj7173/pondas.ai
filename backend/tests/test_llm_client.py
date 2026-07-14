"""LiteLLMClient perf 옵션 테스트 — 프롬프트 캐싱 주입 + 스트리밍 재조립(dev 러너 속도).

캐싱: system + 마지막 문자열 content 메시지에 cache_control(ephemeral). tool_call(content=None)은
불변. 스트리밍: completion(stream=True) 청크를 _collect_stream이 index별로 직접 재조립 —
쪼개진 tool_call arguments를 이어붙여 마지막에 한 번만 json.loads(비스트리밍과 파싱 동일).
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
    client.model, client.stream, client.cache, client.max_tokens = "claude-x", False, True, None
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


def _delta_chunk(*, content=None, tool_calls=None, finish_reason=None):
    """스트리밍 청크 흉내 — choices[0].delta에 content / tool_calls delta를 담는다."""
    delta = types.SimpleNamespace(content=content, tool_calls=tool_calls)
    return types.SimpleNamespace(
        choices=[types.SimpleNamespace(delta=delta, finish_reason=finish_reason)])


def _tc_delta(index, *, id=None, name=None, arguments=None):
    fn = types.SimpleNamespace(name=name, arguments=arguments)
    return types.SimpleNamespace(index=index, id=id, function=fn)


def test_complete_stream_content_only(monkeypatch):
    client = LiteLLMClient.__new__(LiteLLMClient)
    client.model, client.stream, client.cache, client.max_tokens = "claude-x", True, False, None
    seen = {}

    def fake_completion(**kwargs):
        seen["stream"] = kwargs.get("stream")
        return iter([_delta_chunk(content=p) for p in ["fi", "nal ", "answer"]])

    monkeypatch.setattr("litellm.completion", fake_completion)
    resp = client.complete([{"role": "user", "content": "hi"}], [])
    assert seen["stream"] is True
    assert resp.tool_calls is None
    assert resp.content == "final answer"  # content 조각 concat


def test_complete_stream_reassembles_split_tool_args(monkeypatch):
    """핵심 회귀 방지: arguments JSON이 여러 청크로 쪼개져 와도 index별로 이어붙여 파싱한다.
    (stream_chunk_builder가 이 지점에서 JSON을 깨뜨려 'Expecting , delimiter'로 터졌었다.)"""
    client = LiteLLMClient.__new__(LiteLLMClient)
    client.model, client.stream, client.cache, client.max_tokens = "claude-x", True, False, None

    def fake_completion(**kwargs):
        # tool_call 하나가 여러 청크에 걸쳐 도착: id/name 먼저, arguments는 조각조각.
        return iter([
            _delta_chunk(tool_calls=[_tc_delta(0, id="t1", name="write_file")]),
            _delta_chunk(tool_calls=[_tc_delta(0, arguments='{"path": "index.htm')]),
            _delta_chunk(tool_calls=[_tc_delta(0, arguments='l", "content": "<h1>')]),
            _delta_chunk(tool_calls=[_tc_delta(0, arguments='hi</h1>"}')]),
        ])

    monkeypatch.setattr("litellm.completion", fake_completion)
    resp = client.complete([{"role": "user", "content": "build"}], [])
    assert resp.content is None
    assert len(resp.tool_calls) == 1
    c = resp.tool_calls[0]
    assert c.id == "t1" and c.name == "write_file"
    assert c.args == {"path": "index.html", "content": "<h1>hi</h1>"}


def test_complete_stream_multiple_tool_calls(monkeypatch):
    """여러 tool_call이 index로 구분되어 병렬 도착 → 각각 올바르게 재조립."""
    client = LiteLLMClient.__new__(LiteLLMClient)
    client.model, client.stream, client.cache, client.max_tokens = "claude-x", True, False, None

    def fake_completion(**kwargs):
        return iter([
            _delta_chunk(tool_calls=[_tc_delta(0, id="a", name="bash")]),
            _delta_chunk(tool_calls=[_tc_delta(1, id="b", name="write_file")]),
            _delta_chunk(tool_calls=[_tc_delta(0, arguments='{"cmd":')]),
            _delta_chunk(tool_calls=[_tc_delta(1, arguments='{"path":"a"}')]),
            _delta_chunk(tool_calls=[_tc_delta(0, arguments='"ls"}')]),
        ])

    monkeypatch.setattr("litellm.completion", fake_completion)
    resp = client.complete([{"role": "user", "content": "x"}], [])
    calls = {c.name: c.args for c in resp.tool_calls}
    assert calls == {"bash": {"cmd": "ls"}, "write_file": {"path": "a"}}


def test_complete_passes_max_tokens(monkeypatch):
    """max_tokens 설정 시 litellm에 전달 — 미지정이면 Anthropic 기본 캡에 걸려 큰 턴이 잘린다(근본 원인)."""
    captured = {}

    def fake_completion(**kwargs):
        captured.update(kwargs)
        msg = types.SimpleNamespace(tool_calls=None, content="ok")
        return types.SimpleNamespace(
            choices=[types.SimpleNamespace(message=msg, finish_reason="stop")])

    monkeypatch.setattr("litellm.completion", fake_completion)
    client = LiteLLMClient.__new__(LiteLLMClient)
    client.model, client.stream, client.cache, client.max_tokens = "claude-x", False, False, 32000
    client.complete([{"role": "user", "content": "hi"}], [])
    assert captured["max_tokens"] == 32000
    # None(오케 챗 기본)이면 넘기지 않음 — 기존 동작 무변경.
    captured.clear()
    client.max_tokens = None
    client.complete([{"role": "user", "content": "hi"}], [])
    assert "max_tokens" not in captured


def test_stream_truncated_last_call_dropped(monkeypatch):
    """finish_reason=length로 잘린 마지막 tool-call(불완전 JSON)은 버리고 완성된 콜만 살린다.
    (실사례: 디자이너가 큰 파일 여러 개를 한 턴에 뱉다 캡에 걸려 태스크 전체가 죽었다.)"""
    client = LiteLLMClient.__new__(LiteLLMClient)
    client.model, client.stream, client.cache, client.max_tokens = "claude-x", True, False, 32000

    def fake_completion(**kwargs):
        return iter([
            _delta_chunk(tool_calls=[_tc_delta(0, id="a", name="update_plan", arguments='{"steps": []}')]),
            _delta_chunk(tool_calls=[_tc_delta(1, id="b", name="write_file", arguments='{"path": "styles.css"')]),
            _delta_chunk(finish_reason="length"),  # 여기서 잘림 → idx1 args 불완전
        ])

    monkeypatch.setattr("litellm.completion", fake_completion)
    resp = client.complete([{"role": "user", "content": "x"}], [])
    assert [c.name for c in resp.tool_calls] == ["update_plan"]  # 잘린 write_file만 드롭


def test_stream_truncated_no_complete_call_raises(monkeypatch):
    """잘렸는데 완성된 콜이 0개면 빈 content로 'done' 처리되지 말고 명확히 실패해야 한다."""
    import pytest

    client = LiteLLMClient.__new__(LiteLLMClient)
    client.model, client.stream, client.cache, client.max_tokens = "claude-x", True, False, 32000

    def fake_completion(**kwargs):
        return iter([
            _delta_chunk(tool_calls=[_tc_delta(0, id="a", name="write_file", arguments='{"path": "index.htm')]),
            _delta_chunk(finish_reason="length"),
        ])

    monkeypatch.setattr("litellm.completion", fake_completion)
    with pytest.raises(ValueError, match="truncated at max_tokens"):
        client.complete([{"role": "user", "content": "x"}], [])


def test_stream_malformed_without_truncation_raises(monkeypatch):
    """잘리지 않았는데 JSON이 깨졌다면 예상 밖 손상 — 숨기지 않고 예외를 올린다."""
    import pytest

    client = LiteLLMClient.__new__(LiteLLMClient)
    client.model, client.stream, client.cache, client.max_tokens = "claude-x", True, False, 32000

    def fake_completion(**kwargs):
        return iter([
            _delta_chunk(tool_calls=[_tc_delta(0, id="a", name="bash", arguments='{"cmd": broken')]),
            _delta_chunk(finish_reason="tool_calls"),
        ])

    monkeypatch.setattr("litellm.completion", fake_completion)
    with pytest.raises(ValueError):
        client.complete([{"role": "user", "content": "x"}], [])
