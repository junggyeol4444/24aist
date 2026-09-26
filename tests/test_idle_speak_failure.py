"""조용한 구간에 코어가 끊기면 로그가 폭발하던 것.

혼잣말 트리거가 실패해도 다음 시각을 다시 잡지 않으면, 눈치 루프가
0.3초마다 다시 시도하면서 트레이스백을 초당 몇 번씩 찍는다. 회전 로그가
순식간에 밀려서 정작 사고 원인이 담긴 기록이 사라진다.
"""

import asyncio
import logging

from aist.chat_pipeline import ChatPipeline
from aist.config import BroadcastConfig


class _DeadBridge:
    def __init__(self):
        self.tries = 0

    async def proactive_speak(self):
        self.tries += 1
        raise ConnectionResetError("코어가 끊겼다")

    async def say_to_ai(self, *a, **k):
        raise ConnectionResetError("코어가 끊겼다")


def _pipeline(**kw):
    errors = []
    p = ChatPipeline(
        _DeadBridge(),
        BroadcastConfig(idle_proactive_speak=True, idle_gap_min_sec=2,
                        idle_gap_max_sec=3, **kw),
        on_send_error=errors.append,
    )
    return p, errors


def test_failed_idle_speak_backs_off_instead_of_hammering(caplog):
    p, errors = _pipeline()
    caplog.set_level(logging.DEBUG)

    async def run():
        p._next_idle_at = 0            # 지금 말 걸 때가 됐다
        for _ in range(50):            # 눈치 루프가 여러 번 도는 동안
            await p._maybe_idle_speak()

    asyncio.run(run())
    assert p.bridge.tries == 1, f"실패한 혼잣말을 {p.bridge.tries}번 반복했습니다"
    tracebacks = [r for r in caplog.records if r.exc_info]
    assert len(tracebacks) <= 1, "같은 실패로 트레이스백을 반복해서 찍었습니다"


def test_failed_idle_speak_tells_orchestrator_to_reconnect():
    p, errors = _pipeline()

    async def run():
        p._next_idle_at = 0
        await p._maybe_idle_speak()

    asyncio.run(run())
    assert errors, "코어가 끊겼는데 재연결 판단으로 이어지지 않습니다"
