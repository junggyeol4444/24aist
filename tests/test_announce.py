import random
from datetime import datetime

from aist.announce.composer import AnnounceContext, compose, should_post
from aist.config import AnnounceConfig
from aist.persona import Persona

P = Persona()


def test_fixed_style_uses_template():
    cfg = AnnounceConfig(style="fixed", fixed_start_template="시작! {link}")
    out = compose(P, AnnounceContext(kind="start", link="L"), cfg)
    assert out == "시작! L"


def test_varied_offline_pool_appends_link_for_start():
    cfg = AnnounceConfig(style="varied")
    out = compose(P, AnnounceContext(kind="start", link="https://x"), cfg,
                  rng=random.Random(0))
    assert "https://x" in out


def test_varied_end_appends_next_hint():
    cfg = AnnounceConfig(style="varied")
    out = compose(P, AnnounceContext(kind="end", next_stream_hint="다음엔 금요일에"), cfg,
                  rng=random.Random(0))
    assert "다음엔 금요일에" in out


def test_should_post_avoids_late_night():
    cfg = AnnounceConfig(avoid_late_night=True, late_night_window=["01:00", "08:00"])
    assert should_post(datetime(2026, 7, 1, 3, 0), cfg) is False
    assert should_post(datetime(2026, 7, 1, 20, 0), cfg) is True


def test_should_post_wraparound_window():
    cfg = AnnounceConfig(avoid_late_night=True, late_night_window=["23:00", "06:00"])
    assert should_post(datetime(2026, 7, 1, 0, 30), cfg) is False
    assert should_post(datetime(2026, 7, 1, 23, 30), cfg) is False
    assert should_post(datetime(2026, 7, 1, 12, 0), cfg) is True


def test_should_post_can_be_disabled():
    cfg = AnnounceConfig(avoid_late_night=False)
    assert should_post(datetime(2026, 7, 1, 3, 0), cfg) is True
