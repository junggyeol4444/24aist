"""YAML 에서 시각을 따옴표 없이 적으면 숫자가 된다.

  weekly:
    mon: [19:00]     ← YAML 1.1 의 60진수 표기 → 정수 1140

예전에는 여기서 "'int' object has no attribute 'strip'" 트레이스백이 떴다.
점검도 죽고, 24시간 루프도 죽었다.
"""

import pytest
import yaml

from aist.scheduler import Scheduler, _parse_hhmm, as_time_list
from aist.config import SchedulerConfig
from aist.preflight import config_problems


def test_yaml_really_turns_unquoted_time_into_a_number():
    assert yaml.safe_load("a: [19:00]") == {"a": [1140]}


def test_error_message_tells_operator_to_add_quotes():
    with pytest.raises(ValueError) as e:
        _parse_hhmm(1140)
    msg = str(e.value)
    assert "따옴표" in msg and "19:00" in msg


def test_scheduler_skips_bad_entry_instead_of_dying(caplog):
    cfg = SchedulerConfig(weekly={"mon": [1140, "21:00"], "tue": [], "wed": [],
                                  "thu": [], "fri": [], "sat": [], "sun": []})
    s = Scheduler(cfg)
    times = s._times_for("mon")
    assert [t.strftime("%H:%M") for t in times] == ["21:00"]


def test_one_line_instead_of_list_is_accepted():
    assert as_time_list("19:00") == ["19:00"]
    cfg = SchedulerConfig(weekly={"mon": "19:00", "tue": [], "wed": [],
                                  "thu": [], "fri": [], "sat": [], "sun": []})
    assert [t.strftime("%H:%M") for t in Scheduler(cfg)._times_for("mon")] == ["19:00"]


def test_check_reports_it_instead_of_crashing():
    from aist.config import Config
    c = Config()
    c.scheduler.weekly = {"mon": [1140], "tue": [], "wed": [], "thu": [],
                          "fri": [], "sat": [], "sun": []}
    probs = config_problems(c)
    assert any("따옴표" in p for p in probs), probs


def test_plan_does_not_crash_on_bad_time(capsys):
    """`aist plan` 이 트레이스백 대신 일정만 보여줘야 한다."""
    import argparse

    import aist.cli as cli
    from aist.config import Config
    from aist.persona import Persona

    c = Config()
    c.scheduler.weekly = {"mon": [1140], "tue": ["20:00"], "wed": [], "thu": [],
                          "fri": [], "sat": [], "sun": []}
    import pytest as _pytest
    monkey = _pytest.MonkeyPatch()
    monkey.setattr(cli, "_load", lambda args: (c, Persona()))
    try:
        rc = cli.cmd_plan(argparse.Namespace(config="x", persona="y", count=3))
    finally:
        monkey.undo()
    out = capsys.readouterr().out
    assert rc == 0
    assert "Traceback" not in out
