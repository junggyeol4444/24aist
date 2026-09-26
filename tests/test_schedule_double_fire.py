"""같은 슬롯으로 방송이 두 번 나가면 안 된다.

시작 변주를 symmetric 으로 켜면 슬롯보다 일찍 시작할 수 있다(19:00 슬롯을
18:55 시작). 그 방송이 슬롯 시각(19:00) 전에 끝나면 — 코어가 죽어 일찍
내려갔거나 짧게 잡은 경우 — 루프가 19:00 슬롯을 다시 집어서 방송이 한 번
더 나갔다.
"""

import asyncio
from datetime import datetime, timedelta, timezone

import aist.orchestrator as orch_mod
from aist.config import AnnounceConfig, Config, MemoryConfig, SchedulerConfig
from aist.orchestrator import Orchestrator
from aist.persona import Persona


def _run_loop_with_clock(tmp_path, monkeypatch, start_times, jitter_mode="symmetric"):
    cfg = Config(
        scheduler=SchedulerConfig(
            enabled=True, timezone="UTC",
            weekly={"mon": start_times, "tue": start_times, "wed": start_times,
                    "thu": start_times, "fri": start_times, "sat": start_times,
                    "sun": start_times},
            start_jitter_min=5, jitter_mode=jitter_mode),
        announce=AnnounceConfig(on_start=False, on_end=False, pre_announce_minutes=0),
        memory=MemoryConfig(path=str(tmp_path / "m")),
    )
    o = Orchestrator(cfg, Persona())

    clock = {"t": datetime(2026, 9, 14, 18, 50, tzinfo=timezone.utc)}  # 월요일
    monkeypatch.setattr(orch_mod, "_now", lambda tz=None: clock["t"])
    # 여기서 보는 건 스케줄 판단이다 — 코어는 떠 있는 것으로 둔다.
    async def _alive():
        return True
    monkeypatch.setattr(o, "_core_reachable", _alive)

    # 변주는 항상 -5분(일찍 시작)
    class _Rng:
        @staticmethod
        def randint(a, b):
            return a
    monkeypatch.setattr(o.scheduler, "next_start",
                        lambda now, rng=None: _orig_next_start(o, now, _Rng))

    starts = []

    async def fake_sleep(sec):
        clock["t"] = clock["t"] + timedelta(seconds=sec)

    async def fake_broadcast(skip_start_announce=False, retries_left=0, **kw):
        starts.append(clock["t"])
        clock["t"] = clock["t"] + timedelta(minutes=2)   # 2분짜리 방송
        if len(starts) >= 3:
            o.request_stop()

    monkeypatch.setattr(o, "_sleep_or_stop", fake_sleep)
    monkeypatch.setattr(o, "_run_broadcast", fake_broadcast)
    asyncio.run(o.run())
    return starts


def _orig_next_start(o, now, rng):
    from aist.scheduler import Scheduler
    return Scheduler.next_start(o.scheduler, now, rng=rng)


def test_same_slot_does_not_fire_twice(tmp_path, monkeypatch):
    starts = _run_loop_with_clock(tmp_path, monkeypatch, ["19:00"])
    # 하루 한 번 슬롯이면 방송 간격은 하루여야 한다
    assert len(starts) >= 2
    gaps = [(b - a).total_seconds() for a, b in zip(starts, starts[1:])]
    assert all(g > 3600 for g in gaps), f"같은 슬롯이 다시 잡혔습니다: {starts}"


def test_two_slots_a_day_still_both_fire(tmp_path, monkeypatch):
    """슬롯을 두 개 잡아둔 운영자의 의도는 막지 않는다."""
    starts = _run_loop_with_clock(tmp_path, monkeypatch, ["19:00", "22:00"])
    assert len(starts) >= 2
    first_gap = (starts[1] - starts[0]).total_seconds()
    assert 3600 * 2 < first_gap < 3600 * 4, starts
