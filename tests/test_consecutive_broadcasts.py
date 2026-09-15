"""방송을 연달아 했을 때 산출물이 서로 덮이던 것.

3회 연속으로 돌려봐야만 보인다 — 지금까지 어디서도 1회만 돌렸다.
같은 분에 방송이 두 번 시작하면 파일명이 같아져서:
  트랜스크립트 : "a" 모드라 여러 방송이 한 파일에 섞였다
  리포트/컨텐츠 : write_text 라 앞 방송 것을 덮어썼다(소실)

실제 운영에서 나는 경로: 무인운영 재시작 루프에서 방송이 켜자마자 죽고
다시 뜨면 같은 분에 두 번 시작한다. broadcast-now 를 연달아 눌러도 같다.
"""

import asyncio
from datetime import datetime, timezone

from aist.config import Config, MemoryConfig
from aist.memory import Memory
from aist.orchestrator import Orchestrator
from aist.paths import unique_path
from aist.persona import Persona
from aist.report import generate_report
from aist.transcript import Transcript


# --------------------------- unique_path 자체 ------------------------------
def test_unique_path_returns_same_when_free(tmp_path):
    p = tmp_path / "a.md"
    assert unique_path(p) == p


def test_unique_path_adds_suffix_on_collision(tmp_path):
    p = tmp_path / "a.md"
    p.write_text("x", encoding="utf-8")
    p2 = unique_path(p)
    assert p2 != p and p2.name == "a_2.md"
    p2.write_text("y", encoding="utf-8")
    assert unique_path(p).name == "a_3.md"


def test_unique_path_keeps_suffix(tmp_path):
    p = tmp_path / "b.jsonl"
    p.write_text("x", encoding="utf-8")
    assert unique_path(p).name == "b_2.jsonl"


# --------------------------- 트랜스크립트 ----------------------------------
def test_two_transcripts_in_same_minute_do_not_merge(tmp_path):
    start = datetime(2026, 9, 15, 19, 0, tzinfo=timezone.utc)

    t1 = Transcript(str(tmp_path / "tr"))
    p1 = t1.open_session(start)
    t1.log_ai("첫 방송")
    t1.close()

    t2 = Transcript(str(tmp_path / "tr"))
    p2 = t2.open_session(start)          # 같은 분
    t2.log_ai("둘째 방송")
    t2.close()

    assert p1 != p2, "같은 파일이면 두 방송이 섞인다"
    assert "첫 방송" in p1.read_text(encoding="utf-8")
    assert "첫 방송" not in p2.read_text(encoding="utf-8")


# --------------------------- 리포트 ----------------------------------------
def test_second_report_does_not_overwrite_first(tmp_path):
    m = Memory(MemoryConfig(path=str(tmp_path / "mem")))
    m.start_session(); m.end_session()
    r1 = generate_report(m, str(tmp_path / "rep"))
    m.start_session(); m.end_session()
    r2 = generate_report(m, str(tmp_path / "rep"))
    assert r1 != r2, "같은 분이면 앞 리포트를 덮어쓴다"
    assert r1.exists() and r2.exists()


# --------------------------- 방송 3회 연속 ---------------------------------
def test_three_cycles_leave_three_of_each(tmp_path, monkeypatch):
    """방송 3회 → 트랜스크립트·리포트·컨텐츠가 각각 3개여야 한다."""
    cfg = Config()
    cfg.obs.start_stream = False
    cfg.announce.on_start = cfg.announce.on_end = False
    cfg.logging.file_log = False
    cfg.memory.path = str(tmp_path / "mem")
    cfg.logging.dir = str(tmp_path / "logs")
    cfg.logging.reports_dir = str(tmp_path / "rep")
    cfg.logging.content_dir = str(tmp_path / "con")
    cfg.safety.stop_flag_path = str(tmp_path / "STOP")
    cfg.end_judge.max_minutes = 0
    cfg.end_judge.min_minutes = 0
    cfg.end_judge.wind_down.closing_wait_sec = 0
    cfg.end_judge.wind_down.pre_notice_minutes_before_end = 0
    orch = Orchestrator(cfg, Persona())

    class FakeBridge:
        async def connect(self): return self
        async def say_to_ai(self, text, source=None, platform=None, **kw): pass
        async def close(self): pass
        async def recv_loop(self, on_message=None): await asyncio.sleep(3600)

    class FakeObs:
        def connect(self): return self
        def start_stream(self): pass
        def stop_stream(self): pass
        def close(self): pass

    class FakePipeline:
        last_chat_time = None
        def __init__(self, *a, **k): pass
        def on_core_message(self, d): pass
        def is_speaking(self): return False
        def has_pending(self): return False
        async def run(self, source, stop): await stop.wait()

    monkeypatch.setattr("aist.orchestrator.VTuberBridge", lambda c: FakeBridge())
    monkeypatch.setattr("aist.orchestrator.ObsController", lambda c: FakeObs())
    monkeypatch.setattr("aist.orchestrator.ChatPipeline", FakePipeline)
    monkeypatch.setattr("aist.orchestrator.make_chat_source",
                        lambda c: (_ for _ in ()).throw(RuntimeError("채팅 없음")))

    async def main():
        for _ in range(3):
            await orch._run_broadcast()

    asyncio.run(main())

    assert len(orch.memory._sessions) == 3
    for sub in ("logs/transcripts", "rep", "con"):
        files = list((tmp_path / sub).glob("*"))
        assert len(files) == 3, f"{sub}: {len(files)}개 — 서로 덮었다 {[f.name for f in files]}"


def test_state_resets_between_cycles(tmp_path, monkeypatch):
    """한 사이클의 상태가 다음 사이클로 새면 안 된다."""
    cfg = Config()
    cfg.obs.start_stream = False
    cfg.announce.on_start = cfg.announce.on_end = False
    cfg.logging.transcript = False
    cfg.logging.auto_report = cfg.logging.auto_content = False
    cfg.logging.file_log = False
    cfg.memory.path = str(tmp_path / "mem")
    cfg.safety.stop_flag_path = str(tmp_path / "STOP")
    orch = Orchestrator(cfg, Persona())
    orch._core_lost = True
    orch._chat_source_dead = True

    async def boom(*a, **k):
        raise RuntimeError("연결 안 함")

    monkeypatch.setattr("aist.orchestrator.VTuberBridge.connect", boom)
    asyncio.run(orch._run_broadcast())
    assert orch._core_lost is False
    assert orch._chat_source_dead is False
