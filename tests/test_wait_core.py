"""wait-core — 고정 대기 대신 코어가 실제로 뜰 때까지 기다린다.

코어는 모델 로딩으로 뜨는 데 몇 분 걸리기도 한다. 고정 시간만 기다렸다
방송을 시작하면 연결 실패로 그 사이클을 통째로 날린다.
"""

import argparse

import pytest

from aist import cli


def _args(tmp_path, timeout=1):
    return argparse.Namespace(
        config="config/config.example.yaml",
        persona="config/persona.example.yaml",
        timeout=timeout,
    )


def test_returns_0_when_core_reachable(monkeypatch, tmp_path):
    """붙자마자 통과해야 한다(불필요하게 더 안 기다린다)."""
    async def ok(self):
        return None
    monkeypatch.setattr("aist.vtuber_bridge.VTuberBridge.connect", ok)
    monkeypatch.setattr("aist.vtuber_bridge.VTuberBridge.close", ok)
    assert cli.cmd_wait_core(_args(tmp_path)) == 0


def test_returns_1_when_core_never_comes_up(monkeypatch, tmp_path):
    async def boom(self):
        raise OSError("연결 거부")
    monkeypatch.setattr("aist.vtuber_bridge.VTuberBridge.connect", boom)
    monkeypatch.setattr("time.sleep", lambda s: None)
    assert cli.cmd_wait_core(_args(tmp_path, timeout=0)) == 1


def test_retries_until_core_appears(monkeypatch, tmp_path):
    """처음 몇 번 실패해도 뜰 때까지 다시 시도한다(핵심)."""
    calls = {"n": 0}

    async def flaky(self):
        calls["n"] += 1
        if calls["n"] < 3:
            raise OSError("아직 안 뜸")

    async def ok(self):
        return None

    monkeypatch.setattr("aist.vtuber_bridge.VTuberBridge.connect", flaky)
    monkeypatch.setattr("aist.vtuber_bridge.VTuberBridge.close", ok)
    monkeypatch.setattr("time.sleep", lambda s: None)
    assert cli.cmd_wait_core(_args(tmp_path, timeout=60)) == 0
    assert calls["n"] == 3


def test_parser_exposes_wait_core():
    args = cli.build_parser().parse_args(["wait-core", "--timeout", "42"])
    assert args.func is cli.cmd_wait_core
    assert args.timeout == 42
