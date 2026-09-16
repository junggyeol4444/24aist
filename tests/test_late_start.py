"""절전에서 깨어난 뒤 한참 지난 방송을 그대로 시작하면 안 된다.

집 PC 는 잔다. 19시 방송을 기다리다 새벽 3시에 깨어나면, 그대로 시작할
경우 새벽 3시에 "저녁 방송" 이 나간다.
"""

import asyncio
from datetime import datetime, timedelta, timezone

import aist.orchestrator as orch_mod
from aist.config import AnnounceConfig, Config, MemoryConfig, SchedulerConfig
from aist.orchestrator import Orchestrator
from aist.persona import Persona


def _setup(tmp_path, monkeypatch, oversleep_min, grace=30):
    cfg = Config(
        scheduler=SchedulerConfig(
            enabled=True, timezone="UTC",
            weekly={d: ["19:00"] for d in
                    ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]},
            start_jitter_min=0, late_start_grace_min=grace),
        announce=AnnounceConfig(on_start=False, on_end=False, pre_announce_minutes=0),
        memory=MemoryConfig(path=str(tmp_path / "m")),
    )
    o = Orchestrator(cfg, Persona())
    clock = {"t": datetime(2026, 9, 14, 18, 50, tzinfo=timezone.utc)}
    monkeypatch.setattr(orch_mod, "_now", lambda tz=None: clock["t"])

    starts = []
    slept = {"n": 0}

    async def fake_sleep(sec):
        slept["n"] += 1
        # 첫 대기에서 절전이 끼어들어 예정보다 더 지나버린 상황
        extra = timedelta(minutes=oversleep_min) if slept["n"] == 1 else timedelta()
        clock["t"] = clock["t"] + timedelta(seconds=sec) + extra

    async def fake_broadcast(skip_start_announce=False, retries_left=0):
        starts.append(clock["t"])
        clock["t"] = clock["t"] + timedelta(hours=1)
        o.request_stop()

    monkeypatch.setattr(o, "_sleep_or_stop", fake_sleep)
    monkeypatch.setattr(o, "_run_broadcast", fake_broadcast)
    asyncio.run(o.run())
    return starts


def test_very_late_wakeup_skips_the_broadcast(tmp_path, monkeypatch):
    starts = _setup(tmp_path, monkeypatch, oversleep_min=8 * 60)   # 8시간 절전
    assert starts, "다음 방송까지 건너뛰고 나서는 정상 진행해야 한다"
    # 건너뛴 뒤 잡힌 방송은 다음 날 19시대여야 한다(새벽 3시가 아니라)
    assert starts[0].hour == 19, starts


def test_slightly_late_wakeup_still_broadcasts(tmp_path, monkeypatch):
    starts = _setup(tmp_path, monkeypatch, oversleep_min=5)
    assert starts and starts[0].hour == 19


def test_grace_zero_always_starts(tmp_path, monkeypatch):
    starts = _setup(tmp_path, monkeypatch, oversleep_min=8 * 60, grace=0)
    assert starts and starts[0].hour == 3    # 무조건 시작(운영자 선택)
