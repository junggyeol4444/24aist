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
    """기본값 = '사람처럼 방송하는 AI' (운영자 지시: 사람같음은 기본값)."""
    c = Config()
    # 다 반응 + 선별/딜레이 없음 (절대 원칙)
    assert c.broadcast.respond_to_all_chat is True
    assert c.broadcast.artificial_delay_sec == 0.0
    assert c.end_judge.chat_low.enabled is False
    # 사람같음 기본 ON
    assert c.broadcast.opening_greeting is True          # 방송 여는 인사
    assert c.end_judge.wind_down.enabled is True         # 눈치 종료
    assert c.broadcast.idle_proactive_speak is True      # 진행자 혼잣말
    assert c.broadcast.idle_gap_max_sec <= 30            # 조용하면 곧 말 이음
    assert c.announce.style == "varied"                  # 공지 변주
    assert c.announce.history_size > 0                   # 반복 회피
    assert c.announce.avoid_late_night is True           # 새벽 회피
    assert c.announce.pre_announce_minutes == 30         # 사전 예고
    # 시작 시각은 항상 동일 (운영자 지시 — 랜덤 아님)
    assert c.scheduler.start_jitter_min == 0
    assert c.end_judge.end_jitter_min == 0               # 종료도 랜덤 아닌 눈치


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
