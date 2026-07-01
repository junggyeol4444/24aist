from datetime import datetime, timedelta

from aist.config import ChatLow, EndJudgeConfig, WindDown
from aist.end_judge import EndJudge, Phase

START = datetime(2026, 7, 1, 20, 0)


def at(mins):
    return START + timedelta(minutes=mins)


def test_basic_phases():
    cfg = EndJudgeConfig(max_minutes=180, min_minutes=60,
                         wind_down=WindDown(enabled=True, pre_notice_minutes_before_end=10))
    ej = EndJudge(cfg, START)
    assert ej.evaluate(at(30)).phase is Phase.LIVE
    assert ej.evaluate(at(171)).phase is Phase.PRE_NOTICE   # 180-10=170 이후
    assert ej.evaluate(at(181)).phase is Phase.END


def test_min_time_guaranteed_even_if_scheduled_end_is_soon():
    # 23:50 시작, 정해진 종료 00:00 → 10분뿐이지만 최소 60분 보장
    start = datetime(2026, 7, 1, 23, 50)
    cfg = EndJudgeConfig(max_minutes=300, min_minutes=60, scheduled_end_hhmm="00:00")
    ej = EndJudge(cfg, start)
    assert ej.planned_end == start + timedelta(minutes=60)


def test_scheduled_end_before_max():
    start = datetime(2026, 7, 1, 22, 0)
    cfg = EndJudgeConfig(max_minutes=300, min_minutes=60, scheduled_end_hhmm="00:00")
    ej = EndJudge(cfg, start)
    assert ej.planned_end == datetime(2026, 7, 2, 0, 0)
    assert ej.planned_trigger == "scheduled_end"


def test_chat_low_triggers_after_min_only():
    cfg = EndJudgeConfig(max_minutes=300, min_minutes=60,
                         chat_low=ChatLow(enabled=True, quiet_minutes=20))
    ej = EndJudge(cfg, START)
    # 최소 시간 전 + 조용 → 아직 LIVE
    assert ej.evaluate(at(50), last_chat_time=at(20)).phase is Phase.LIVE
    # 최소 시간 후 + 20분 조용 → END(chat_low)
    d = ej.evaluate(at(90), last_chat_time=at(60))
    assert d.phase is Phase.END and d.trigger == "chat_low"


def test_chat_low_disabled_keeps_live_when_quiet():
    cfg = EndJudgeConfig(max_minutes=300, min_minutes=60,
                         chat_low=ChatLow(enabled=False))
    ej = EndJudge(cfg, START)
    assert ej.evaluate(at(200), last_chat_time=at(10)).phase is Phase.LIVE


def test_end_jitter_is_deterministic_and_bounded():
    import random
    cfg = EndJudgeConfig(max_minutes=180, min_minutes=60, end_jitter_min=20)
    ej = EndJudge(cfg, START, rng=random.Random(1))
    delta = (ej.hard_end - START).total_seconds() / 60
    assert 160 <= delta <= 200


def test_no_wind_down_means_no_pre_notice():
    cfg = EndJudgeConfig(max_minutes=180, min_minutes=60,
                         wind_down=WindDown(enabled=False))
    ej = EndJudge(cfg, START)
    assert ej.evaluate(at(179)).phase is Phase.LIVE
    assert ej.evaluate(at(181)).phase is Phase.END
