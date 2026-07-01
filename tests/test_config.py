import textwrap

import pytest

from aist.config import (
    Config, ConfigError, FloodHandling, WindDown, load_config,
)


def _write(tmp_path, text):
    p = tmp_path / "config.yaml"
    p.write_text(textwrap.dedent(text), encoding="utf-8")
    return p


def test_example_config_loads():
    cfg = load_config("config/config.example.yaml")
    assert cfg.platform == "twitch"
    assert cfg.end_judge.max_minutes == 180
    # 중첩 dataclass 가 dict 가 아니라 타입으로 변환됐는지(핵심 회귀)
    assert isinstance(cfg.broadcast.flood_handling, FloodHandling)
    assert isinstance(cfg.end_judge.wind_down, WindDown)
    assert cfg.broadcast.flood_handling.enabled is False


def test_partial_config_uses_defaults(tmp_path):
    p = _write(tmp_path, """
        platform: twitch
        end_judge:
          max_minutes: 90
    """)
    cfg = load_config(p)
    assert cfg.end_judge.max_minutes == 90
    assert cfg.end_judge.min_minutes == 60          # 기본값
    assert cfg.broadcast.respond_to_all_chat is True  # 절대 원칙 디폴트


def test_defaults_reflect_principles():
    """기본값이 기획안의 디폴트(다 반응/딜레이0/변주0)인지."""
    c = Config()
    assert c.broadcast.respond_to_all_chat is True
    assert c.broadcast.artificial_delay_sec == 0.0
    assert c.scheduler.start_jitter_min == 0
    assert c.end_judge.end_jitter_min == 0
    assert c.end_judge.chat_low.enabled is False
    assert c.announce.style == "varied"
    assert c.announce.avoid_late_night is True


def test_min_greater_than_max_rejected(tmp_path):
    p = _write(tmp_path, """
        end_judge:
          max_minutes: 60
          min_minutes: 120
    """)
    with pytest.raises(ConfigError):
        load_config(p)


def test_bad_platform_rejected(tmp_path):
    p = _write(tmp_path, "platform: kakao\n")
    with pytest.raises(ConfigError):
        load_config(p)


def test_missing_file():
    with pytest.raises(ConfigError):
        load_config("definitely/not/here.yaml")
