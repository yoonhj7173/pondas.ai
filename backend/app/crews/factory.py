"""텍스트 에이전트 LLM 클라이언트 — litellm.completion 1회 호출(과거 CrewAI 대체).

기획/리서치 등 글쓰기팀의 에이전트는 "역할지침(system) + 조립된 프롬프트(user)"로 LLM을 딱
한 번 부르면 된다. 멀티에이전트 오케스트레이션(핸드오프·리뷰루프)은 우리 graph_engine이 하지
CrewAI가 아니었다 → 무거운 프레임워크를 걷어내고 오케스트레이터와 동일한 litellm 경로로 통일.

계약: 프로덕션=TextLLM(litellm), 테스트=ScriptedLLM(미리 정한 응답). 둘 다
    .complete(system, prompt) -> (output, tokens_in, tokens_out) 만 지키면 worker_core 텍스트
    경로가 동일하게 동작한다(라이브 키 없이 테스트 가능).
"""

from __future__ import annotations

from app.config import settings


def _heuristic_tokens(prompt: str, output: str, ti: int = 0, to: int = 0) -> tuple[int, int]:
    """토큰 수 — 프로바이더가 usage를 주면 그걸, 없으면 길이 휴리스틱(≈4 chars/token)."""
    return (ti or max(1, len(prompt) // 4), to or max(1, len(output) // 4))


class TextLLM:
    """프로덕션 텍스트 에이전트 — litellm.completion(system=역할, user=프롬프트) 1회.

    오케스트레이터 LiteLLMClient와 같은 litellm 경로라 bare 모델명(claude-opus-4-8 등)도
    Anthropic으로 정상 라우팅된다(과거 CrewAI 래퍼의 provider 오탐 이슈가 사라짐).
    timeout/num_retries 필수 — 없으면 프로바이더 행이 Celery 워커를 무한 점유(감사 P0).
    """

    def __init__(self, model: str):
        self.model = model

    def complete(self, system: str, prompt: str) -> tuple[str, int, int]:
        from litellm import completion

        resp = completion(
            model=self.model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            timeout=settings.llm_request_timeout_sec,
            num_retries=settings.llm_num_retries,
        )
        content = resp.choices[0].message.content or ""
        usage = getattr(resp, "usage", None)
        ti = int(getattr(usage, "prompt_tokens", 0) or 0)
        to = int(getattr(usage, "completion_tokens", 0) or 0)
        return content, *_heuristic_tokens(prompt, content, ti, to)


class ScriptedLLM:
    """테스트용 — 미리 정한 응답을 순서대로 반환(라이브 API 키 불필요)."""

    def __init__(self, responses: list[str]):
        self._responses = list(responses)
        self._i = 0

    def complete(self, system: str, prompt: str) -> tuple[str, int, int]:
        r = self._responses[min(self._i, len(self._responses) - 1)]
        self._i += 1
        return r, *_heuristic_tokens(prompt, r)
