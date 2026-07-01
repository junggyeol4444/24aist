import random
from datetime import datetime

from aist.config import SchedulerConfig
from aist.scheduler import Scheduler


def cfg(**kw):
    return SchedulerConfig(**kw)


def test_next_slot_same_day():
    sc = Scheduler(cfg(weekly={"wed": ["19:00", "21:00"]}))
    now = datetime(2026, 7, 1, 18, 0)  # 수요일
    assert sc.next_slot(now) == datetime(2026, 7, 1, 19, 0)


def test_next_slot_picks_earliest_future_time():
    sc = Scheduler(cfg(weekly={"wed": ["19:00", "21:00"]}))
    now = datetime(2026, 7, 1, 20, 0)
    assert sc.next_slot(now) == datetime(2026, 7, 1, 21, 0)


def test_rest_day_skipped():
    # 일요일 휴방 → 다음 평일로
    sc = Scheduler(cfg(weekly={"mon": ["19:00"], "sun": []}))
    sunday = datetime(2026, 7, 5, 12, 0)
    assert sc.is_rest_day(sunday) is True
    assert sc.next_slot(sunday) == datetime(2026, 7, 6, 19, 0)


def test_all_rest_returns_none():
    sc = Scheduler(cfg(weekly={d: [] for d in
                               ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]}))
    assert sc.next_slot(datetime(2026, 7, 1, 12, 0)) is None


def test_jitter_zero_is_exact():
    sc = Scheduler(cfg(weekly={"wed": ["19:00"]}, start_jitter_min=0))
    now = datetime(2026, 7, 1, 10, 0)
    assert sc.next_start(now) == datetime(2026, 7, 1, 19, 0)


def test_jitter_deterministic_with_seed():
    sc = Scheduler(cfg(weekly={"wed": ["19:00"]}, start_jitter_min=60, jitter_mode="after"))
    now = datetime(2026, 7, 1, 10, 0)
    a = sc.next_start(now, rng=random.Random(123))
    b = sc.next_start(now, rng=random.Random(123))
    assert a == b
    # "after" 는 늦게만 → 슬롯 이상
    assert a >= datetime(2026, 7, 1, 19, 0)
    assert a <= datetime(2026, 7, 1, 20, 0)


def test_seconds_until_floors_at_zero():
    now = datetime(2026, 7, 1, 19, 0)
    past = datetime(2026, 7, 1, 18, 0)
    assert Scheduler.seconds_until(past, now) == 0.0
