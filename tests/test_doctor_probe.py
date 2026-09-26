"""`aist doctor` 의 채팅 플랫폼 점검 표시.

각 플랫폼 probe 는 실패해도 예외 대신 설명 문자열을 돌려준다. doctor 가
그걸 무조건 [OK] 로 찍으면, 토큰이 틀려도 "모두 OK" 로 끝난다 — 방송 전
점검이 거짓말이 된다.
"""

import asyncio
import types

import pytest

from aist.chat.base import ProbeResult


def _levels(monkeypatch, level):
    """doctor 가 그 level 을 어떻게 찍는지 (태그, 반환코드)."""
    import aist.cli as cli
    from aist.config import Config
    from aist.persona import Persona

    cfg = Config(platform="twitch")
    monkeypatch.setattr(cli, "_load", lambda args: (cfg, Persona()))

    import aist.preflight as pf
    monkeypatch.setattr(pf, "missing", lambda c: [])
    monkeypatch.setattr(pf, "core_frontend_ready", lambda: (True, ""))
    monkeypatch.setattr(pf, "core_conf_ready", lambda: (True, ""))
    monkeypatch.setattr(pf, "core_deps_ready", lambda: (True, "ok"))
    monkeypatch.setattr(pf, "core_python_ok", lambda: (True, "3.12"))

    class _Src:
        platform = "twitch"

        async def probe(self):
            return ProbeResult(level, "테스트 사유")

        async def close(self):
            return None

    import aist.chat.factory as factory
    monkeypatch.setattr(factory, "make_single_source", lambda p, c: _Src())

    # 코어 WS / OBS 는 실패하도록 두고(어차피 여기선 확인 대상이 아님)
    # 플랫폼 줄만 본다.
    args = types.SimpleNamespace(config="x", persona="y", log="INFO")
    return cli.cmd_doctor, args


@pytest.mark.parametrize("level,tag", [("ok", "[OK]"), ("warn", "[!]"), ("fail", "[X]")])
def test_probe_level_is_shown(monkeypatch, capsys, level, tag):
    fn, args = _levels(monkeypatch, level)
    fn(args)
    out = capsys.readouterr().out
    assert f"{tag} twitch" in out, out


def test_failed_probe_is_not_reported_as_ok(monkeypatch, capsys):
    fn, args = _levels(monkeypatch, "fail")
    fn(args)
    out = capsys.readouterr().out
    assert "모두 OK" not in out


def test_chzzk_probe_failure_is_not_ok(monkeypatch):
    from aist.chat.chzzk import ChzzkChat
    src = ChzzkChat("채널ID")

    def boom():
        raise RuntimeError("치지직: 방송 중이 아니거나 chatChannelId 를 못 받음")

    monkeypatch.setattr(src, "_fetch_tokens", boom)
    res = asyncio.run(src.probe())
    assert res.level != "ok"
    assert "channel_id" in str(res)
