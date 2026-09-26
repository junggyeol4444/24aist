"""코어가 {"type": "error"} 로 대화를 망쳤다고 알려올 때.

실제 코어(single_conversation.py)는 대화 도중 예외가 나면 오류만 보내고
'대화 끝' 신호를 안 보낸다. 코어 쪽 메시지 큐가 'active conversation'
상태로 굳어서, 그 뒤의 채팅이 전부 처리되지 않았다(실제 코어로 재현 —
끼어들기(interrupt)를 보내야 풀린다). 예전 파이프라인은 이 오류를 통째로
버리고 90초를 기다렸고, 로그에는 "웹UI 가 안 붙어 있으면…" 이라는 엉뚱한
안내가 찍혔으며, 세 번 겹치면 웹UI 탓을 하며 방송을 내렸다.
"""
import asyncio
import time

from aist.chat_pipeline import ChatPipeline
from aist.config import BroadcastConfig


class Bridge:
    def __init__(self):
        self.interrupts = 0

    async def interrupt(self):
        self.interrupts += 1


_START = {"type": "control", "text": "conversation-chain-start"}
_END = {"type": "control", "text": "conversation-chain-end"}
# 실제 코어가 보낸 문구 그대로(images 가 이상한 text-input 으로 재현).
_ABORT = {"type": "error",
          "message": "Conversation error: 'str' object has no attribute 'get'"}
# 문장 하나만 실패한 경우 — 코어는 나머지를 말하고 정상적으로 끝낸다.
_PARTIAL = {"type": "error",
            "message": "Error processing response: tts failed"}


def _expire(p):
    p._error_deadline = time.monotonic() - 0.01


def test_aborted_chain_is_unstuck_quickly_without_mute_strike():
    async def go():
        br = Bridge()
        mute = []
        p = ChatPipeline(br, BroadcastConfig(core_mute_max_strikes=1),
                         on_core_mute=lambda: mute.append(1))
        p._mark_busy()
        p.on_core_message(_START)
        p.on_core_message(_ABORT)
        assert p._busy_now() is True        # 끝 신호가 올 여유를 준다
        _expire(p)
        assert p._busy_now() is False       # 90초가 아니라 곧바로 풀린다
        await asyncio.sleep(0)
        assert br.interrupts == 1           # 코어 큐를 끼어들기로 푼다
        assert mute == []                   # 웹UI 탓이 아니다
        assert p._busy_streak == 0
    asyncio.run(go())


def test_error_with_proper_end_is_not_interrupted():
    """오류 뒤에 끝 신호가 제대로 오면 끊지 않는다."""
    async def go():
        br = Bridge()
        p = ChatPipeline(br, BroadcastConfig())
        p._mark_busy()
        p.on_core_message(_START)
        p.on_core_message(_ABORT)
        p.on_core_message(_END)
        _expire(p)
        assert p._busy_now() is False
        await asyncio.sleep(0)
        assert br.interrupts == 0
    asyncio.run(go())


def test_one_failed_sentence_does_not_cut_the_rest():
    """문장 하나 실패는 막힌 게 아니다 — 나머지 말을 자르면 안 된다."""
    async def go():
        br = Bridge()
        p = ChatPipeline(br, BroadcastConfig())
        p._mark_busy()
        p.on_core_message(_START)
        p.on_core_message(_PARTIAL)
        p._busy_since = time.monotonic()
        assert p._error_deadline == 0.0
        assert p._busy_now() is True        # 계속 말하는 중
        await asyncio.sleep(0)
        assert br.interrupts == 0
    asyncio.run(go())


def test_repeated_errors_are_reported_with_streak_and_reset():
    seen = []
    p = ChatPipeline(Bridge(), BroadcastConfig(),
                     on_core_error=lambda m, n: seen.append((m, n)))

    def bad_chain():
        p.on_core_message(_START)
        p.on_core_message(_PARTIAL)
        p.on_core_message(_END)

    bad_chain()
    bad_chain()
    assert [n for _m, n in seen] == [1, 2]
    assert "tts failed" in seen[0][0]
    p.on_core_message(_START)
    p.on_core_message(_END)                 # 한 번 멀쩡하면 끊긴다
    bad_chain()
    assert seen[-1][1] == 1


def test_orchestrator_takes_broadcast_down_naming_core_error(
        tmp_path, monkeypatch, caplog):
    """오류가 연달아 나면 방송을 내리고, 코어가 보낸 오류를 로그에 적는다.

    웹UI 탓("enable_proxy 확인")을 하면 운영자는 엉뚱한 데를 고친다.
    """
    import logging

    from aist.config import Config
    from aist.orchestrator import Orchestrator
    from aist.persona import Persona

    cfg = Config()
    cfg.obs.start_stream = False
    cfg.announce.on_start = False
    cfg.announce.on_end = False
    cfg.logging.transcript = False
    cfg.logging.auto_report = False
    cfg.logging.auto_content = False
    cfg.logging.file_log = False
    cfg.broadcast.opening_greeting = False
    cfg.broadcast.idle_proactive_speak = False
    cfg.memory.path = str(tmp_path / "memory")
    cfg.safety.stop_flag_path = str(tmp_path / "STOP")
    cfg.end_judge.min_minutes = 60
    cfg.end_judge.max_minutes = 60
    orch = Orchestrator(cfg, Persona())

    class FakeBridge:
        async def connect(self): return self
        async def say_to_ai(self, *a, **k): pass
        async def interrupt(self, *a, **k): pass
        async def close(self): pass

        async def recv_loop(self, on_message=None):
            for _ in range(3):
                on_message(_START)
                on_message(_ABORT)
                on_message(_END)
                await asyncio.sleep(0)
            await asyncio.sleep(3600)

    async def no_teardown(*a, **k):
        pass

    monkeypatch.setattr("aist.orchestrator.VTuberBridge", lambda c: FakeBridge())
    monkeypatch.setattr("aist.orchestrator.make_chat_source",
                        lambda c: (_ for _ in ()).throw(RuntimeError("없음")))
    monkeypatch.setattr(orch, "_teardown", no_teardown)
    monkeypatch.setattr("aist.orchestrator._CORE_ERROR_MIN_SPAN_SEC", 0.0)

    caplog.set_level(logging.INFO)

    async def main():
        await asyncio.wait_for(orch._run_broadcast(), 10)

    asyncio.run(main())
    text = "\n".join(r.getMessage() for r in caplog.records)
    assert "'str' object has no attribute 'get'" in text
    assert "이번 방송 종료" in text
    assert "enable_proxy" not in text
    kinds = [e["kind"] for e in orch.memory._sessions[-1].get("events", [])]
    assert "core_error" in kinds and "core_error_gave_up" in kinds
    assert "ended_early" in kinds


def test_error_after_chain_end_does_not_cut_next_reply():
    """코어는 말을 다 하고 '끝' 신호를 보낸 뒤 대화 기록을 저장한다.

    그 저장이 실패하면(디스크 가득·백신이 파일을 잡음) 끝 신호 '뒤에'
    "Conversation error" 가 온다. 그 사이 우리는 다음 채팅을 이미 보냈다.
    그걸 막힌 것으로 보고 끊으면 멀쩡한 다음 대답이 잘린다.
    """
    async def go():
        br = Bridge()
        seen = []
        p = ChatPipeline(br, BroadcastConfig(),
                         on_core_error=lambda m, n: seen.append(n))
        p.on_core_message(_START)
        p.on_core_message(_END)
        p._mark_busy()                      # 다음 채팅을 보냄
        p.on_core_message(_ABORT)           # 앞 대화의 기록 저장 실패
        assert p._error_deadline == 0.0     # 끊을 시각을 잡지 않는다
        p._busy_since = time.monotonic()
        assert p._busy_now() is True        # 다음 대답은 그대로 진행
        await asyncio.sleep(0)
        assert br.interrupts == 0
        assert seen == [1]                  # 그래도 리포트에는 남는다
    asyncio.run(go())


def test_brief_error_burst_does_not_take_broadcast_down(tmp_path, monkeypatch):
    """백신이 파일을 몇 초 잡은 정도로 24시간 방송이 내려가면 안 된다.

    실제 코어로 막아보니 채팅이 몰릴 때 11초 만에 3번이 찼다.
    """
    from aist.config import Config
    from aist.orchestrator import Orchestrator
    from aist.persona import Persona

    cfg = Config()
    cfg.obs.start_stream = False
    cfg.announce.on_start = False
    cfg.announce.on_end = False
    cfg.logging.transcript = False
    cfg.logging.auto_report = False
    cfg.logging.auto_content = False
    cfg.logging.file_log = False
    cfg.broadcast.opening_greeting = False
    cfg.broadcast.idle_proactive_speak = False
    cfg.memory.path = str(tmp_path / "memory")
    cfg.safety.stop_flag_path = str(tmp_path / "STOP")
    orch = Orchestrator(cfg, Persona())
    stopped = []

    class FakeBridge:
        async def connect(self): return self
        async def say_to_ai(self, *a, **k): pass
        async def interrupt(self, *a, **k): pass
        async def close(self): pass

        async def recv_loop(self, on_message=None):
            for _ in range(5):
                on_message(_START)
                on_message(_ABORT)
                on_message(_END)
                await asyncio.sleep(0)
            stopped.append(orch._core_error_dead)
            orch._stop.set()
            await asyncio.sleep(3600)

    async def no_teardown(*a, **k):
        pass

    monkeypatch.setattr("aist.orchestrator.VTuberBridge", lambda c: FakeBridge())
    monkeypatch.setattr("aist.orchestrator.make_chat_source",
                        lambda c: (_ for _ in ()).throw(RuntimeError("없음")))
    monkeypatch.setattr(orch, "_teardown", no_teardown)
    asyncio.run(asyncio.wait_for(orch._run_broadcast(), 10))
    assert stopped == [""]      # 5번 연달아 났어도 몇 초 사이면 버틴다
