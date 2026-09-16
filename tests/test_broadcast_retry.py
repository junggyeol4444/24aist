"""사고로 일찍 끝난 방송을 같은 슬롯에서 다시 켠다.

예전에는 한 번 죽으면 그 날 방송이 통째로 날아갔다 — 19시에 켜서 19시
2분에 인터넷이 잠깐 끊기면, 운영자가 자는 사이 2분짜리 방송만 남고 다음
방송은 내일이었다. 무인 운영에서 그건 정상일 수 없다.
"""

import asyncio
from datetime import timedelta

from aist.config import Config
from aist.orchestrator import Orchestrator, _now
from aist.persona import Persona


class _FakeEj:
    def __init__(self, cfg, minutes_left):
        self.planned_end = _now(cfg.scheduler.timezone) + timedelta(minutes=minutes_left)


def _orc(**sched):
    cfg = Config()
    cfg.scheduler.enabled = True
    for k, v in sched.items():
        setattr(cfg.scheduler, k, v)
    return Orchestrator(cfg, Persona()), cfg


def test_retry_allowed_when_plenty_of_time_left():
    o, cfg = _orc(retry_min_left_min=20)
    assert o._enough_time_left(_FakeEj(cfg, 120)) is True


def test_no_retry_when_broadcast_was_almost_over():
    """거의 끝나가던 방송을 다시 켜면 1~2분짜리 방송이 된다."""
    o, cfg = _orc(retry_min_left_min=20)
    assert o._enough_time_left(_FakeEj(cfg, 3)) is False


def test_retry_floor_is_ten_minutes_even_if_operator_sets_zero():
    """운영자가 0 을 넣어도 10분 미만 남았으면 다시 켜지 않는다."""
    o, cfg = _orc(retry_min_left_min=0)
    assert o._enough_time_left(_FakeEj(cfg, 5)) is False
    assert o._enough_time_left(_FakeEj(cfg, 30)) is True


def test_retry_loop_stops_after_retry_max():
    """재시도는 반드시 끝나야 한다 — 무한히 켰다 껐다 하면 안 된다."""
    o, cfg = _orc(retry_max=2, retry_backoff_sec=0)
    calls = []

    async def fake_run(skip_start_announce=False, retries_left=0):
        calls.append((skip_start_announce, retries_left))
        return "retry" if retries_left > 0 else "normal"

    o._run_broadcast = fake_run
    o.scheduler.next_slot = lambda now: now
    o.scheduler.next_start = lambda now: now
    o.scheduler.seconds_until = lambda at, now: 0

    async def go():
        # 한 슬롯을 돌고 나면 멈춘다
        async def stop_soon():
            await asyncio.sleep(0.05)
            o._stop.set()
        await asyncio.gather(o.run(), stop_soon())

    asyncio.run(go())
    # 첫 방송 + 재시도 2회 = 3번, 그 뒤로는 안 켠다
    assert [c[1] for c in calls[:3]] == [2, 1, 0]
    # 재시도할 때는 시작 공지를 다시 내지 않는다
    assert [c[0] for c in calls[1:3]] == [True, True]
