"""공지용 LLM 호출이 방송을 멈추면 안 된다.

compose() 는 네트워크 호출을 한다. async 함수 안에서 그냥 부르면 이벤트
루프가 통째로 멈춘다 — 그동안 채팅도, 종료 판단도, 말 끝 신호도 안 돈다.
SDK 기본 타임아웃은 10분이라 그만큼 멈출 수 있다.
"""

import asyncio
import time

import pytest

import aist.orchestrator as orch_mod
from aist.config import AnnounceConfig, Config, LlmConfig, MemoryConfig
from aist.orchestrator import Orchestrator
from aist.persona import Persona


def _orch(tmp_path, compose_delay):
    cfg = Config(
        announce=AnnounceConfig(on_start=True, on_end=True,
                                avoid_late_night=False, style="varied"),
        memory=MemoryConfig(path=str(tmp_path / "memory")),
    )
    o = Orchestrator(cfg, Persona())

    def slow_compose(*a, **k):
        time.sleep(compose_delay)     # 블로킹 네트워크 호출 흉내
        return "느린 공지"

    return o, slow_compose


def test_announce_does_not_freeze_the_event_loop(tmp_path, monkeypatch):
    o, slow = _orch(tmp_path, 0.6)
    monkeypatch.setattr(orch_mod, "compose", slow)

    async def main():
        ticks = 0

        async def ticker():
            nonlocal ticks
            while True:
                await asyncio.sleep(0.05)
                ticks += 1

        t = asyncio.create_task(ticker())
        await o._announce("start", orch_mod._now("Asia/Seoul"))
        t.cancel()
        return ticks

    ticks = asyncio.run(main())
    # 루프가 멈췄다면 0~1 번밖에 못 돈다.
    assert ticks >= 5, f"공지 만드는 동안 이벤트 루프가 멈췄습니다 (ticks={ticks})"


def test_llm_timeout_default_and_config():
    from aist.llm import LLMClient
    from aist.config import Secrets

    assert LLMClient(LlmConfig(), Secrets())._timeout() == 30.0
    assert LLMClient(LlmConfig(timeout_sec=5), Secrets())._timeout() == 5.0
    # 0/음수/쓰레기 값이 '무한 대기'로 바뀌면 안 된다
    assert LLMClient(LlmConfig(timeout_sec=0), Secrets())._timeout() == 30.0
    assert LLMClient(LlmConfig(timeout_sec="이상한값"), Secrets())._timeout() == 30.0


def test_openai_client_gets_timeout(monkeypatch):
    """SDK 기본 10분을 그대로 쓰지 않는지."""
    import sys
    import types

    seen = {}

    class _Client:
        def __init__(self, **kw):
            seen.update(kw)
            self.chat = types.SimpleNamespace(
                completions=types.SimpleNamespace(create=self._create))

        def _create(self, **kw):
            msg = types.SimpleNamespace(content="ok")
            return types.SimpleNamespace(
                choices=[types.SimpleNamespace(message=msg)])

    fake = types.ModuleType("openai")
    fake.OpenAI = _Client
    monkeypatch.setitem(sys.modules, "openai", fake)

    from aist.config import Secrets
    from aist.llm import LLMClient
    c = LLMClient(LlmConfig(provider="openai", timeout_sec=12), Secrets(openai_api_key="k"))
    assert c.complete("s", "u") == "ok"
    assert seen.get("timeout") == 12.0
