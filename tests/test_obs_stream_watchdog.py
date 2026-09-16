"""방송 중 송출이 혼자 내려가는 상황 — OBS 는 스트림 키 오류·네트워크
문제로 실제로 송출을 끊는다. 그러면 방송인은 아무도 안 보는 데서 몇
시간을 떠들게 된다."""

import asyncio

from aist.config import Config
from aist.obs_control import ObsError
from aist.orchestrator import Orchestrator
from aist.persona import Persona


class _FakeObs:
    """states 는 "live" | "down" | "unreachable" 을 순서대로 돌려준다."""

    def __init__(self, states, start_raises=False, reconnect_ok=False):
        self._states = list(states)
        self.starts = 0
        self.reconnects = 0
        self.start_raises = start_raises
        self.reconnect_ok = reconnect_ok

    def stream_state(self):
        return self._states.pop(0) if self._states else "live"

    def start_stream(self):
        self.starts += 1
        if self.start_raises:
            raise ObsError("스트림 시작 실패: 스트림 키 오류")

    def reconnect(self):
        self.reconnects += 1
        return self.reconnect_ok


def _orc(**obs_kw):
    cfg = Config()
    cfg.obs.start_stream = True
    cfg.obs.stream_check_sec = 0.001
    for k, v in obs_kw.items():
        setattr(cfg.obs, k, v)
    o = Orchestrator(cfg, Persona())
    o._next_obs_check = 0.0
    o._obs_restarts = 0
    return o, cfg


def _run(o, obs, times):
    async def go():
        out = []
        for _ in range(times):
            o._next_obs_check = 0.0          # 간격을 기다리지 않는다
            out.append(await o._check_stream_alive(obs))
        return out
    return asyncio.run(go())


def test_stream_drop_is_restarted_then_gives_up():
    o, _ = _orc(stream_restart_max=2)
    obs = _FakeObs(["down"] * 3)
    assert _run(o, obs, 3) == [True, True, False]
    assert obs.starts == 2      # 두 번 다시 켜보고 포기


def test_healthy_stream_is_left_alone():
    o, _ = _orc()
    obs = _FakeObs(["live"] * 4)
    assert _run(o, obs, 4) == [True] * 4
    assert obs.starts == 0


def test_obs_death_is_detected_and_ends_broadcast():
    """OBS 가 아예 대답을 안 하면 송출도 확실히 끊긴 것이다.

    실제로 OBS 프로세스를 죽여보니, 예전 코드는 60초가 지나도록 아무
    말도 없이 방송을 계속 내보냈다 — 인코더가 없으니 시청자에게는
    아무것도 안 가는데.
    """
    o, _ = _orc(unreachable_max=3)
    obs = _FakeObs(["unreachable"] * 3)
    assert _run(o, obs, 3) == [True, True, False]
    assert obs.reconnects == 3      # 매번 다시 붙어보긴 한다


def test_obs_comes_back_is_not_treated_as_death():
    """잠깐 못 붙었다가 다시 붙으면 방송을 내리지 않는다."""
    o, _ = _orc(unreachable_max=2)
    obs = _FakeObs(["unreachable", "live", "unreachable", "live"], reconnect_ok=True)
    assert _run(o, obs, 4) == [True] * 4


def test_recovered_stream_resets_the_counter():
    """다시 켜져서 한동안 멀쩡했으면, 다음 사고는 처음부터 센다."""
    o, _ = _orc(stream_restart_max=1)
    obs = _FakeObs(["down", "live", "live", "down", "live"])
    assert _run(o, obs, 5) == [True] * 5
    assert obs.starts == 2


def test_restart_failure_ends_broadcast():
    o, _ = _orc(stream_restart_max=3)
    obs = _FakeObs(["down"], start_raises=True)
    assert _run(o, obs, 1) == [False]


def test_watchdog_off_when_operator_runs_the_stream():
    """start_stream=false 면 송출은 운영자 몫 — 건드리지 않는다."""
    o, cfg = _orc()
    cfg.obs.start_stream = False
    obs = _FakeObs(["down", "down"])
    assert _run(o, obs, 2) == [True, True]
    assert obs.starts == 0


def test_stop_stream_is_quiet_when_obs_already_gone(caplog):
    """OBS 가 죽어서 방송을 내리는 길에서, 뒷정리가 ERROR 를 찍으면 안 된다.

    "OBS 에 먼저 connect() 해야 합니다" 가 ERROR 로 찍히면 운영자에게는
    프로그램이 잘못된 것처럼 보인다 — 실제 로그에서 그렇게 나왔다.
    """
    import logging

    from aist.config import ObsConfig
    from aist.obs_control import ObsController

    o = ObsController(ObsConfig(start_stream=True))
    o._client = None
    with caplog.at_level(logging.INFO, logger="aist.obs"):
        o.stop_stream()          # 예외도, ERROR 도 없어야 한다
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]
