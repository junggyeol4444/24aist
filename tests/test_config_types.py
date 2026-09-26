"""설정 값의 타입이 어긋나도 방송 도중에 죽지 않는다.

운영자는 config.yaml 을 메모장으로 고친다. 따옴표 하나 차이로
  max_minutes: "180"   → 문자열
가 되면 예전에는 방송 시작 직후 TypeError 로 죽었다. 그 메시지로는
운영자가 아무것도 못 고친다.
"""

import pytest
import yaml

from aist.config import ConfigError, load_config


def _write(tmp_path, text):
    p = tmp_path / "c.yaml"
    p.write_text(text, encoding="utf-8")
    return p


def test_quoted_number_is_accepted(tmp_path):
    cfg = load_config(_write(tmp_path, 'end_judge:\n  max_minutes: "180"\n'
                                       'vtuber:\n  connect_timeout_sec: "10"\n'))
    assert cfg.end_judge.max_minutes == 180
    assert isinstance(cfg.end_judge.max_minutes, int)
    assert cfg.vtuber.connect_timeout_sec == 10.0


def test_quoted_bool_is_accepted(tmp_path):
    cfg = load_config(_write(tmp_path, 'obs:\n  start_stream: "false"\n'))
    assert cfg.obs.start_stream is False


def test_number_where_text_expected(tmp_path):
    cfg = load_config(_write(tmp_path, "obs:\n  password: 1234\n"))
    assert cfg.obs.password == "1234"


def test_scalar_where_list_expected(tmp_path):
    cfg = load_config(_write(tmp_path, "platforms: twitch\n"))
    assert cfg.platforms == ["twitch"]


def test_unreadable_number_says_what_to_fix(tmp_path):
    with pytest.raises(ConfigError) as e:
        load_config(_write(tmp_path, "end_judge:\n  max_minutes: 삼십\n"))
    msg = str(e.value)
    assert "end_judge.max_minutes" in msg and "정수" in msg


def test_broadcast_run_path_survives_string_numbers(tmp_path):
    """실제로 쓰이는 자리(종료 판단)까지 숫자로 도착해야 한다."""
    from datetime import datetime, timezone

    from aist.end_judge import EndJudge

    cfg = load_config(_write(tmp_path,
                             'end_judge:\n  min_minutes: "30"\n  max_minutes: "90"\n'))
    ej = EndJudge(cfg.end_judge, datetime(2026, 9, 15, 19, 0, tzinfo=timezone.utc))
    assert (ej.planned_end - ej.start).total_seconds() == 90 * 60


def test_cli_prints_korean_error_not_traceback(capsys, tmp_path):
    import aist.cli as cli

    p = _write(tmp_path, "end_judge:\n  max_minutes: 삼십\n")
    rc = cli.main(["--config", str(p), "plan"])
    out = capsys.readouterr().out
    assert rc == 1
    assert "Traceback" not in out
    assert "[오류]" in out and "max_minutes" in out
