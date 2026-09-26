"""종료 공지의 "다음엔 ~" 안내가 틀린 정보를 주던 것.

완전 자동 루프(run)를 처음 끝까지 돌려보다 찾았다.
주 1회 화요일 방송이면 화요일에 끝내면서 "다음엔 화요일" 이라고 하는데,
시청자는 내일로 알아듣지만 실제로는 일주일 뒤다.
(기획안 4-4 "다음엔 O요일에" 형식 자체는 유지하되 며칠 뒤인지에 따라
 말을 바꾼다 — 요일만으로는 정보가 틀리게 전달된다)
"""

import tempfile
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

import aist.orchestrator as om
from aist.config import Config
from aist.orchestrator import Orchestrator
from aist.persona import Persona

KST = ZoneInfo("Asia/Seoul")
DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def _hint(weekly, now, monkeypatch):
    cfg = Config()
    cfg.scheduler.weekly = weekly
    cfg.memory.path = tempfile.mkdtemp()
    orch = Orchestrator(cfg, Persona())
    monkeypatch.setattr(om, "_now", lambda tz: now)
    return orch._next_stream_hint()


def _only(day, times):
    w = {d: [] for d in DAYS}
    w[day] = times
    return w


def test_tomorrow_says_tomorrow(monkeypatch):
    """매일 방송이면 '내일' 이라고 해야 한다."""
    h = _hint({d: ["19:00"] for d in DAYS},
              datetime(2026, 9, 15, 22, 0, tzinfo=KST), monkeypatch)
    assert "내일" in h


def test_same_weekday_next_week_is_not_ambiguous(monkeypatch):
    """주 1회면 '화요일' 만으로는 내일로 오해된다."""
    h = _hint(_only("tue", ["19:00"]),
              datetime(2026, 9, 15, 22, 0, tzinfo=KST), monkeypatch)   # 화요일 밤
    assert "다음 주" in h, f"일주일 뒤인데 구분이 없다: {h!r}"


def test_later_today_says_today(monkeypatch):
    h = _hint(_only("tue", ["19:00", "23:30"]),
              datetime(2026, 9, 15, 22, 0, tzinfo=KST), monkeypatch)
    assert "오늘" in h


def test_few_days_ahead_uses_weekday(monkeypatch):
    """2~6일 뒤는 요일만으로 충분하다(기획안 형식 유지)."""
    w = {d: [] for d in DAYS}
    for d in ("mon", "tue", "wed", "thu", "fri"):
        w[d] = ["19:00"]
    h = _hint(w, datetime(2026, 9, 18, 22, 0, tzinfo=KST), monkeypatch)  # 금 → 월
    assert "월요일" in h and "다음 주" not in h and "내일" not in h


def test_two_weeks_out_uses_date(monkeypatch):
    """2주 이상이면 요일로는 못 알아듣는다 — 날짜를 준다."""
    cfg = Config()
    cfg.scheduler.weekly = _only("tue", ["19:00"])
    cfg.memory.path = tempfile.mkdtemp()
    orch = Orchestrator(cfg, Persona())
    now = datetime(2026, 9, 15, 22, 0, tzinfo=KST)
    monkeypatch.setattr(om, "_now", lambda tz: now)
    # 다음 슬롯이 2주 뒤라고 가정
    monkeypatch.setattr(orch.scheduler, "next_slot",
                        lambda n, **k: datetime(2026, 9, 29, 19, 0, tzinfo=KST))
    h = orch._next_stream_hint()
    assert "9월 29일" in h, h


def test_no_upcoming_broadcast_says_nothing(monkeypatch):
    h = _hint({d: [] for d in DAYS},
              datetime(2026, 9, 15, 22, 0, tzinfo=KST), monkeypatch)
    assert h == ""


@pytest.mark.parametrize("hour", range(0, 24, 3))
def test_hint_never_empty_when_broadcast_scheduled(hour, monkeypatch):
    h = _hint({d: ["19:00"] for d in DAYS},
              datetime(2026, 9, 15, hour, 0, tzinfo=KST), monkeypatch)
    assert h.startswith("다음엔 ") and h.endswith("에")
