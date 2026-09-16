"""방송 중 송출이 혼자 내려가는 상황 — OBS 는 스트림 키 오류·네트워크
문제로 실제로 송출을 끊는다. 그러면 방송인은 아무도 안 보는 데서 몇
시간을 떠들게 된다."""

import asyncio

from aist.config import Config
from aist.obs_control import ObsError
from aist.orchestrator import Orchestrator
from aist.persona import Persona


class _FakeObs:
    def __init__(self, states, start_raises=False):
        self._states = list(states)
        self.starts = 0
        self.start_raises = start_raises

    def is_streaming(self):
        return self._states.pop(0) if self._states else True

    def start_stream(self):
        self.starts += 1
        if self.start_raises:
            raise ObsError("스트림 시작 실패: 스트림 키 오류")


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
    obs = _FakeObs([False, False, False])
    assert _run(o, obs, 3) == [True, True, False]
    assert obs.starts == 2      # 두 번 다시 켜보고 포기


def test_healthy_stream_is_left_alone():
    o, _ = _orc()
    obs = _FakeObs([True, True, True, True])
    assert _run(o, obs, 4) == [True] * 4
    assert obs.starts == 0


def test_unknown_state_does_not_end_broadcast():
    """상태를 모를 때(None) 방송을 내리면 안 된다 — 멀쩡한 방송이 꺼진다."""
    o, _ = _orc()
    obs = _FakeObs([None, None, None])
    assert _run(o, obs, 3) == [True] * 3
    assert obs.starts == 0


def test_recovered_stream_resets_the_counter():
    """다시 켜져서 한동안 멀쩡했으면, 다음 사고는 처음부터 센다."""
    o, _ = _orc(stream_restart_max=1)
    obs = _FakeObs([False, True, True, False, True])
    assert _run(o, obs, 5) == [True] * 5
    assert obs.starts == 2


def test_restart_failure_ends_broadcast():
    o, _ = _orc(stream_restart_max=3)
    obs = _FakeObs([False], start_raises=True)
    assert _run(o, obs, 1) == [False]


def test_watchdog_off_when_operator_runs_the_stream():
    """start_stream=false 면 송출은 운영자 몫 — 건드리지 않는다."""
    o, cfg = _orc()
    cfg.obs.start_stream = False
    obs = _FakeObs([False, False])
    assert _run(o, obs, 2) == [True, True]
    assert obs.starts == 0
