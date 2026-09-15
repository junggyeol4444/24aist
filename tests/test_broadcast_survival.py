"""24시간 무인 운영에서 실제로 터진 것들의 회귀 테스트.

전부 "가짜 코어를 띄우고 실제로 돌려보다가" 발견한 증상이다.
단위 테스트로는 안 잡히던 것들이라, 증상 자체를 재현하는 형태로 잠근다.

  1) Ctrl+C 로 끄면 뒷정리가 통째로 안 돌아 OBS 스트림이 켜진 채 남았다
  2) 마무리 인사 뒤에도 채팅에 계속 답하다가 뚝 끊겼다 (기획안 4-3 위반)
  3) 코어가 죽어도 프로세스가 좀비로 살아 무음 송출이 최대 3시간 갔다
"""

import asyncio

import pytest

from aist.config import Config
from aist.orchestrator import Orchestrator
from aist.persona import Persona


def _orch(tmp_path, **over):
    cfg = Config()
    cfg.obs.start_stream = False
    cfg.announce.on_start = False
    cfg.announce.on_end = False
    cfg.logging.transcript = False
    cfg.logging.auto_report = False
    cfg.logging.auto_content = False
    cfg.logging.file_log = False
    cfg.memory.path = str(tmp_path / "memory")
    cfg.safety.stop_flag_path = str(tmp_path / "STOP")
    for k, v in over.items():
        setattr(cfg, k, v)
    return Orchestrator(cfg, Persona())


# --------------------------- 1) 취소돼도 뒷정리는 돈다 ----------------------
def test_teardown_runs_even_when_cancelled(tmp_path, monkeypatch):
    """Ctrl+C 로 취소돼도 _teardown 이 반드시 돌아야 한다.

    안 돌면 obs.stop_stream() 이 호출되지 않아 스트림이 켜진 채 남는다.
    실측: 수정 전에는 트랜스크립트의 broadcast_end 가 0개였다.
    """
    orch = _orch(tmp_path)
    called = {"teardown": 0}

    async def fake_teardown(*a, **k):
        called["teardown"] += 1

    async def never_ends(*a, **k):
        await asyncio.sleep(3600)

    monkeypatch.setattr(orch, "_teardown", fake_teardown)
    # 코어 연결/채팅/OBS 는 이 테스트의 관심사가 아니다 — 루프까지만 간다.
    monkeypatch.setattr("aist.orchestrator.VTuberBridge.connect", never_ends)

    async def main():
        task = asyncio.ensure_future(orch._run_broadcast())
        await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(main())
    assert called["teardown"] == 1


# --------------------------- 2) 마무리 인사가 마지막이어야 한다 -------------
def test_chat_stops_before_closing_greeting(tmp_path, monkeypatch):
    """마무리 인사 '전에' 채팅 유입이 끊겨야 한다.

    안 끊으면 "오늘 고마웠어요~" 하고 나서 closing_wait_sec(기본 45초)
    동안 새 채팅에 계속 답하다가 뚝 끊긴다. 기획안 4-3 이 금지한 것이다.
    """
    orch = _orch(tmp_path)
    order = []

    async def fake_teardown(obs, bridge, pipeline, pipeline_task, chat_stop, *a, **k):
        order.append(("teardown", chat_stop.is_set()))

    class FakeBridge:
        async def connect(self): return self
        async def say_to_ai(self, text, source=None, platform=None):
            if "마무리 인사" in text:
                order.append(("closing_cue", None))
        async def close(self): pass
        async def recv_loop(self, on_message=None): await asyncio.sleep(3600)

    class FakeObs:
        def connect(self): return self
        def start_stream(self): pass
        def stop_stream(self): pass
        def close(self): pass

    monkeypatch.setattr(orch, "_teardown", fake_teardown)
    monkeypatch.setattr("aist.orchestrator.VTuberBridge", lambda cfg: FakeBridge())
    monkeypatch.setattr("aist.orchestrator.ObsController", lambda cfg: FakeObs())
    monkeypatch.setattr("aist.orchestrator.make_chat_source",
                        lambda cfg: (_ for _ in ()).throw(RuntimeError("채팅 없음")))

    # 곧바로 종료 판단이 나게 한다.
    orch.cfg.end_judge.min_minutes = 0
    orch.cfg.end_judge.max_minutes = 0
    orch.cfg.end_judge.wind_down.closing_wait_sec = 0
    orch.cfg.end_judge.wind_down.pre_notice_minutes_before_end = 0

    # chat_stop 이 언제 걸리는지 보려고 ChatPipeline 을 가로챈다.
    real_pipeline = []

    class FakePipeline:
        last_chat_time = None
        def __init__(self, *a, **k): real_pipeline.append(self)
        def on_core_message(self, d): pass
        def is_speaking(self): return False
        def has_pending(self): return False
        async def run(self, source, stop): await stop.wait()

    monkeypatch.setattr("aist.orchestrator.ChatPipeline", FakePipeline)
    asyncio.run(orch._run_broadcast())

    kinds = [k for k, _ in order]
    assert "closing_cue" in kinds, "마무리 인사가 나가야 한다"
    assert kinds.index("closing_cue") < kinds.index("teardown")
    # teardown 시점엔 이미 꺼져 있어야 하고, 그 전(인사 시점)에 꺼진 것이다.
    assert order[-1] == ("teardown", True)


# --------------------------- 3) 코어가 죽으면 방송을 내린다 -----------------
def test_core_loss_triggers_reconnect_then_gives_up(tmp_path):
    """재연결을 시도하고, 다 실패하면 포기(=방송 종료)해야 한다.

    포기하지 않고 계속 돌면 아바타는 멈추고 스트림만 무음으로 나간다.
    프로세스가 끝나야 무인운영.bat 의 재시작 루프도 걸린다.
    """
    orch = _orch(tmp_path)
    orch.cfg.vtuber.reconnect_max_attempts = 3
    orch.cfg.vtuber.reconnect_backoff_sec = 0

    tries = {"n": 0}

    class DeadBridge:
        async def reconnect_once(self):
            tries["n"] += 1
            return False

    ok = asyncio.run(orch._recover_core(DeadBridge()))
    assert ok is False
    assert tries["n"] == 3


def test_core_loss_recovers_when_core_comes_back(tmp_path):
    orch = _orch(tmp_path)
    orch.cfg.vtuber.reconnect_max_attempts = 5
    orch.cfg.vtuber.reconnect_backoff_sec = 0
    tries = {"n": 0}

    class FlakyBridge:
        async def reconnect_once(self):
            tries["n"] += 1
            return tries["n"] >= 2      # 두 번째에 살아남

    assert asyncio.run(orch._recover_core(FlakyBridge())) is True
    assert tries["n"] == 2


def test_operator_can_disable_mid_broadcast_reconnect(tmp_path):
    """운영자가 끄면 예전 동작(재연결 안 함)으로 돌아가되, 방송은 내린다."""
    orch = _orch(tmp_path)
    orch.cfg.vtuber.reconnect_during_broadcast = False

    class Bridge:
        async def reconnect_once(self):
            raise AssertionError("재연결을 시도하면 안 된다")

    assert asyncio.run(orch._recover_core(Bridge())) is False


# --------------------------- 4) 중단 스위치 --------------------------------
def test_stop_flag_requests_stop(tmp_path):
    orch = _orch(tmp_path)
    assert orch._check_stop_flag() is False
    orch.stop_flag.raise_("테스트")
    assert orch._check_stop_flag() is True
    assert orch._stop.is_set()


def test_stale_stop_flag_does_not_kill_next_broadcast(tmp_path, monkeypatch):
    """지난 방송이 남긴 스위치가 다음 방송을 켜자마자 끄면 안 된다."""
    orch = _orch(tmp_path)
    orch.stop_flag.raise_("지난 방송")

    async def boom(*a, **k):
        raise RuntimeError("연결 안 함")

    monkeypatch.setattr("aist.orchestrator.VTuberBridge.connect", boom)
    asyncio.run(orch._run_broadcast())
    assert orch.stop_flag.raised() is False


# --------------------------- 5) 금지어 대응 --------------------------------
def test_banned_word_in_ai_speech_is_logged_and_interrupted(tmp_path, caplog):
    orch = _orch(tmp_path)
    orch.cfg.safety.banned_words = ["사고단어"]
    interrupted = {"n": 0}

    class Bridge:
        async def interrupt(self, heard_text=""):
            interrupted["n"] += 1

    events = []

    class T:
        def log_event(self, kind, **kw): events.append((kind, kw))

    async def main():
        orch._watch_output(
            {"type": "audio", "display_text": {"text": "이건 사고단어 입니다"}},
            Bridge(), T())
        await asyncio.sleep(0)

    asyncio.run(main())
    assert interrupted["n"] == 1
    assert events and events[0][0] == "banned_word"


def test_no_banned_words_means_no_work(tmp_path):
    orch = _orch(tmp_path)

    class Bridge:
        async def interrupt(self, heard_text=""):
            raise AssertionError("기본값에선 끼어들면 안 된다")

    orch._watch_output({"type": "audio", "display_text": {"text": "아무 말"}},
                       Bridge(), None)


# --------------------------- 6) 디스크가 차도 방송은 제대로 내려간다 --------
def test_memory_save_failure_does_not_break_teardown(tmp_path, monkeypatch):
    """디스크가 차면 기억 저장에서 OSError 가 올라와 종료 공지까지 막혔다."""
    from pathlib import Path as _P
    from aist.config import MemoryConfig
    from aist.memory import Memory

    m = Memory(MemoryConfig(path=str(tmp_path / "mem")))
    m.start_session()

    def no_space(self, *a, **k):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(_P, "write_text", no_space)
    m.end_session()          # 예외가 올라오면 안 된다


def test_transcript_write_failure_stops_quietly(tmp_path, caplog):
    """핸들이 죽으면 채팅마다 ValueError 가 났다(로그 폭발 + 콜백 예외)."""
    from datetime import datetime, timezone
    from aist.chat.base import ChatMessage
    from aist.transcript import Transcript

    t = Transcript(str(tmp_path / "tr"))
    t.open_session(datetime.now(timezone.utc))
    t._fh.close()            # 디스크 오류로 핸들이 죽은 상황

    for _ in range(50):
        t.log_chat(ChatMessage(author="닉", text="안녕", platform="twitch"))

    errors = [r for r in caplog.records if r.levelname == "ERROR"]
    assert len(errors) == 1        # 한 번만 알리고 조용히 포기


def test_teardown_continues_after_one_step_fails(tmp_path, monkeypatch):
    """한 단계가 터져도 OBS 종료·종료 공지까지 간다."""
    orch = _orch(tmp_path)
    orch.cfg.announce.on_end = True
    orch.cfg.announce.discord.enabled = False
    orch.cfg.announce.naver_cafe.enabled = False
    done = {"obs_stop": 0, "announce": 0}

    class Obs:
        def stop_stream(self): done["obs_stop"] += 1
        def close(self): pass

    class Bridge:
        async def close(self): pass

    class BadTranscript:
        path = None
        def close(self): raise OSError(28, "No space left on device")

    async def fake_announce(kind, now):
        done["announce"] += 1

    monkeypatch.setattr(orch, "_announce", fake_announce)
    monkeypatch.setattr(orch.memory, "end_session",
                        lambda: (_ for _ in ()).throw(OSError("disk")))

    asyncio.run(orch._teardown(Obs(), Bridge(), None, None, None,
                               None, transcript=BadTranscript()))
    assert done["obs_stop"] == 1
    assert done["announce"] == 1
