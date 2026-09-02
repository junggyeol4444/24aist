"""리허설 채팅 — 플랫폼·키 없이 방송 루프를 돌려볼 수 있어야 한다."""

import asyncio

import pytest

from aist.chat.base import ChatMessage
from aist.chat.factory import make_single_source
from aist.chat.rehearsal import RehearsalChat
from aist.config import load_config


def _take(source, n, timeout=5.0):
    async def go():
        out = []
        agen = source.messages()
        async for m in agen:
            out.append(m)
            if len(out) >= n:
                break
        await agen.aclose()
        return out
    return asyncio.run(asyncio.wait_for(go(), timeout))


def test_yields_chat_messages():
    msgs = _take(RehearsalChat(interval_sec=0.01), 5)
    assert len(msgs) == 5
    assert all(isinstance(m, ChatMessage) for m in msgs)
    assert all(m.platform == "rehearsal" for m in msgs)
    assert all(m.author and m.text for m in msgs)


def test_superchat_appears():
    """후원 반응 경로도 리허설에서 밟히도록 가끔 슈퍼챗을 섞는다."""
    msgs = _take(RehearsalChat(interval_sec=0.01, superchat_every=3), 9)
    sc = [m for m in msgs if m.is_superchat]
    assert sc, "슈퍼챗이 하나도 안 나왔다"
    assert all(m.amount for m in sc)


def test_superchat_can_be_disabled():
    msgs = _take(RehearsalChat(interval_sec=0.01, superchat_every=0), 6)
    assert not any(m.is_superchat for m in msgs)


def test_factory_makes_rehearsal_source():
    cfg = load_config("config/config.example.yaml")
    assert isinstance(make_single_source("rehearsal", cfg), RehearsalChat)


def test_rehearsal_needs_no_extra_package():
    """리허설은 추가 패키지 없이 돌아야 한다(그게 요점)."""
    from aist import preflight
    cfg = load_config("config/config.example.yaml")
    cfg.platform = "rehearsal"
    cfg.platforms = []
    chat_needs = [n for n in preflight.needs(cfg) if "채팅" in n.feature]
    assert chat_needs == []


def test_probe_describes_itself():
    assert "리허설" in asyncio.run(RehearsalChat().probe())


def _run_rehearse(monkeypatch, tmp_path, **overrides):
    """cmd_rehearse 를 돌리고 orchestrator 에 넘어간 설정을 돌려준다.

    rehearse 는 코어 연결이 진짜라서 websockets 가 없으면 시작 전에
    멈춘다. 그 판단 자체는 옳지만, 여기서 보려는 건 '설정을 어떻게
    바꿔서 넘기는가' 라서 설치 여부와 무관하게 통과시킨다.
    (CI 의 pytest 잡은 옵션 의존성을 깔지 않는다.)
    """
    import argparse
    from aist import cli, preflight

    captured = {}

    class FakeOrch:
        def __init__(self, cfg, persona):
            captured["cfg"] = cfg

        async def run_one_now(self):
            return None

    monkeypatch.setattr("aist.orchestrator.Orchestrator", FakeOrch)
    monkeypatch.setattr(preflight.Need, "installed",
                        property(lambda self: True))

    args = argparse.Namespace(
        config="config/config.example.yaml",
        persona="config/persona.example.yaml",
        minutes=1, rehearsal_dir=str(tmp_path / "reh"),
    )
    for k, v in overrides.items():
        setattr(args, k, v)
    assert cli.cmd_rehearse(args) == 0
    return captured["cfg"]


def test_rehearse_writes_only_to_rehearsal_dir(monkeypatch, tmp_path):
    """리허설이 진짜 기억·리포트를 건드리면 안 된다.

    가짜 시청자/후원이 장기기억에 들어가면 다음 실제 방송 공지가
    "저번 방송 땐 N명 왔었고" 처럼 인용한다.
    """
    cfg = _run_rehearse(monkeypatch, tmp_path)
    reh = tmp_path / "reh"
    for path in (cfg.memory.path, cfg.logging.dir,
                 cfg.logging.reports_dir, cfg.logging.content_dir):
        assert str(reh) in path, f"실제 경로로 샜다: {path}"


def test_rehearse_disables_stream_and_announce(monkeypatch, tmp_path):
    """송출·공지가 실수로 나가면 안 된다."""
    cfg = _run_rehearse(monkeypatch, tmp_path)
    assert cfg.obs.start_stream is False
    assert cfg.obs.launch_if_not_running is False
    assert cfg.announce.discord.enabled is False
    assert cfg.announce.naver_cafe.enabled is False
    assert cfg.platform == "rehearsal"


def test_rehearse_blocks_without_websockets(monkeypatch, tmp_path):
    """코어 연결은 진짜라서 websockets 가 없으면 시작 전에 멈춘다."""
    import argparse
    from aist import cli, preflight

    monkeypatch.setattr(preflight.Need, "installed",
                        property(lambda self: False))
    rc = cli.cmd_rehearse(argparse.Namespace(
        config="config/config.example.yaml",
        persona="config/persona.example.yaml",
        minutes=1, rehearsal_dir=str(tmp_path / "reh"),
    ))
    assert rc == 1


def test_rehearsal_platform_passes_validation(tmp_path):
    """factory 가 받는 플랫폼을 설정 검증이 거부하면 안 된다.

    cmd_rehearse 는 로드 뒤에 platform 을 바꾸므로 이 불일치가 가려져
    있었다. config.yaml 에 직접 적으면 ConfigError 로 죽었다.
    """
    import textwrap
    from aist.config import load_config

    p = tmp_path / "config.yaml"
    p.write_text(textwrap.dedent("""
        platform: rehearsal
    """), encoding="utf-8")
    cfg = load_config(str(p))
    assert cfg.platform == "rehearsal"
    assert cfg.active_platforms() == ["rehearsal"]


def test_unknown_platform_still_rejected(tmp_path):
    import textwrap
    import pytest as _pytest
    from aist.config import ConfigError, load_config

    p = tmp_path / "config.yaml"
    p.write_text(textwrap.dedent("""
        platform: 없는플랫폼
    """), encoding="utf-8")
    with _pytest.raises(ConfigError):
        load_config(str(p))
