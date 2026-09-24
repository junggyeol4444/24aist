"""방송 중에 코어가 죽었을 때 — 무인 운영이 스스로 되살아나는지.

실제로 `aist run` 으로 방송하다 코어를 죽여 보니, 방송만 내리고 "다음 방송:
7일 뒤" 를 찍은 채 그대로 대기했다. 무인운영.bat 은 `aist run` 이 끝나야
코어를 다시 띄우므로, 코어는 영영 안 살아나고 다음 슬롯도 실패한다.

고친 뒤(같은 실험): `aist run` 이 종료 코드 3 으로 끝남 → 감시 루프가 코어를
다시 띄움 → 새로 뜬 `aist run` 이 같은 방송을 원래 끝 시각 그대로 이어서
켜고, OBS 웹UI 를 새로고침해 다시 붙인다.
"""
import asyncio
import json
from datetime import datetime, timedelta, timezone

import pytest

from aist.config import Config, EndJudgeConfig, MemoryConfig
from aist.end_judge import EndJudge
from aist.memory import Memory
from aist.orchestrator import EXIT_CORE_RESTART, Orchestrator
from aist.persona import Persona
from aist.transcript import Transcript


def _orch(tmp_path):
    cfg = Config()
    cfg.obs.start_stream = False
    cfg.announce.on_start = False
    cfg.announce.on_end = False
    cfg.logging.file_log = False
    cfg.memory.path = str(tmp_path / "memory")
    cfg.safety.stop_flag_path = str(tmp_path / "STOP")
    cfg.scheduler.timezone = "UTC"
    cfg.scheduler.retry_backoff_sec = 0
    return Orchestrator(cfg, Persona())


def _now():
    return datetime.now(timezone.utc)


# ------------------------------------------------ 코어가 죽으면 프로그램을 끝낸다
def test_코어에_못_붙으면_프로그램을_끝내고_이어_켤_기록을_남긴다(tmp_path):
    o = _orch(tmp_path)
    calls = []

    async def dead_core(**kw):
        calls.append(kw)
        o._core_unreachable = True
        st = kw["slot_state"]
        st["start"] = _now().isoformat()
        st["planned_end"] = (_now() + timedelta(hours=2)).isoformat()
        o._write_slot(st)
        return "retry"

    o._run_broadcast = dead_core
    keep_going = asyncio.run(o._run_slot(_now(), skip_announce=False))
    assert keep_going is False
    assert o.exit_code == EXIT_CORE_RESTART
    assert len(calls) == 1              # 이 프로세스 안에서 헛되이 재시도하지 않는다
    assert o._slot_file().is_file()     # 다시 뜬 프로그램이 이어 켠다


def test_시작도_못_한_슬롯도_기록해서_늦게라도_시작한다(tmp_path):
    o = _orch(tmp_path)

    async def no_core(**kw):
        o._core_unreachable = True
        return "aborted"

    o._run_broadcast = no_core
    slot = _now()
    assert asyncio.run(o._run_slot(slot, skip_announce=True)) is False
    st = json.loads(o._slot_file().read_text(encoding="utf-8"))
    assert st["slot"] == slot.isoformat() and not st.get("start")
    assert st["announced"] is True       # 사전 공지는 다시 안 낸다


def test_코어가_멀쩡하면_예전처럼_같은_프로세스에서_다시_켠다(tmp_path):
    o = _orch(tmp_path)
    results = iter(["retry", "normal"])
    seen = []

    async def flaky(**kw):
        seen.append((kw["resuming"], dict(kw["resume"] or {})))
        if not kw["slot_state"].get("start"):
            kw["slot_state"]["start"] = "2026-09-24T10:00:00+00:00"
            kw["slot_state"]["planned_end"] = "2026-09-24T13:00:00+00:00"
        return next(results)

    o._run_broadcast = flaky
    assert asyncio.run(o._run_slot(_now())) is True
    assert o.exit_code == 0
    assert seen[0][0] is False
    # 두 번째는 '이어 켜기' 이고, 처음 시작·끝 시각을 들고 간다
    assert seen[1][0] is True
    assert seen[1][1]["planned_end"] == "2026-09-24T13:00:00+00:00"


# ------------------------------------------------ 다시 뜬 프로그램이 이어 켠다
def _write_state(o, **st):
    o._slot_file().parent.mkdir(parents=True, exist_ok=True)
    o._slot_file().write_text(json.dumps(st), encoding="utf-8")


def test_끝_시각이_충분히_남았으면_이어_켠다(tmp_path):
    o = _orch(tmp_path)
    now = _now()
    _write_state(o, slot=(now - timedelta(minutes=30)).isoformat(),
                 start=(now - timedelta(minutes=30)).isoformat(),
                 planned_end=(now + timedelta(hours=2)).isoformat(), resumes=0)
    got = []

    async def fake_slot(slot, skip_announce=False, resume=None):
        got.append((slot, skip_announce, resume))
        o._stop.set()
        return True

    o._run_slot = fake_slot
    asyncio.run(o.run())
    assert len(got) == 1
    slot, skip, resume = got[0]
    assert skip is True                      # 시작 공지를 또 내지 않는다
    assert resume["resumes"] == 1


def test_끝나기_직전이면_이어_켜지_않는다(tmp_path):
    o = _orch(tmp_path)
    now = _now()
    _write_state(o, slot=now.isoformat(), start=now.isoformat(),
                 planned_end=(now + timedelta(minutes=3)).isoformat(), resumes=0)
    assert o._pending_slot() is None
    assert not o._slot_file().exists()


def test_이어_켜기를_끝없이_반복하지_않는다(tmp_path):
    o = _orch(tmp_path)
    now = _now()
    _write_state(o, slot=now.isoformat(), start=now.isoformat(),
                 planned_end=(now + timedelta(hours=2)).isoformat(),
                 resumes=o.cfg.scheduler.retry_max)
    assert o._pending_slot() is None


def test_시작_못_한_슬롯은_늦은_시작_허용_범위_안에서만(tmp_path):
    o = _orch(tmp_path)
    now = _now()
    _write_state(o, slot=(now - timedelta(minutes=5)).isoformat(), resumes=0)
    assert o._pending_slot() is not None
    _write_state(o, slot=(now - timedelta(hours=3)).isoformat(), resumes=0)
    assert o._pending_slot() is None


def test_깨진_기록은_무시한다(tmp_path):
    o = _orch(tmp_path)
    o._slot_file().parent.mkdir(parents=True, exist_ok=True)
    o._slot_file().write_text("{깨짐", encoding="utf-8")
    assert o._pending_slot() is None


# ------------------------------------------------ 이어 켠 방송은 같은 방송이다
def test_이어_켠_방송은_원래_끝_시각을_지킨다():
    start = datetime(2026, 9, 24, 19, 0, tzinfo=timezone.utc)
    end = datetime(2026, 9, 24, 22, 0, tzinfo=timezone.utc)
    ej = EndJudge(EndJudgeConfig(min_minutes=60, max_minutes=180), start,
                  planned_end=end)
    assert ej.planned_end == end
    # 21:30 에 다시 켜도 새벽 0:30 까지 가지 않는다
    assert ej.evaluate(datetime(2026, 9, 24, 22, 1, tzinfo=timezone.utc)).phase.name == "END"


def test_기록_파일은_이어서_쓴다(tmp_path):
    t = Transcript(str(tmp_path))
    first = t.open_session(_now())
    t.log_ai("끊기기 전 발화")
    t.close()
    t2 = Transcript(str(tmp_path))
    again = t2.open_session(_now(), continue_path=first)
    t2.log_ai("다시 켠 뒤 발화")
    t2.close()
    assert again == first
    texts = [json.loads(line).get("text") for line in
             first.read_text(encoding="utf-8").splitlines()]
    assert "끊기기 전 발화" in texts and "다시 켠 뒤 발화" in texts


def test_프로그램이_다시_떠도_회차가_쪼개지지_않는다(tmp_path):
    cfg = MemoryConfig(path=str(tmp_path / "mem"))
    m = Memory(cfg)
    m.start_session()
    first_start = m._cur["start"]
    m._cur["viewers"].append("시청자A")
    m._save_current()
    # 프로그램이 통째로 죽고 다시 뜸
    m2 = Memory(cfg)
    m2.start_session(resume=True)
    assert m2._cur["start"] == first_start
    assert "시청자A" in m2._cur["viewers"]
    assert "crashed" not in m2._cur
    m2.end_session()
    m3 = Memory(cfg)
    starts = [s["start"] for s in m3._sessions]
    assert starts.count(first_start) == 1


def test_끊겨_있을_때_보낸_채팅은_연결_문제로_알린다():
    from aist.config import VTuberConfig
    from aist.vtuber_bridge import VTuberBridge
    b = VTuberBridge(VTuberConfig())
    with pytest.raises(ConnectionError):
        asyncio.run(b.say_to_ai("안녕"))
