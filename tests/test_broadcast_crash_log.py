"""방송이 예상 못 한 오류로 멈추면 운영자 로그에 남는지.

실제로 코드에 문제를 만들어 돌려보니, 운영자가 다음 날 펴보는
data/logs/aist.log 에는 이렇게만 남았다:

  === 방송 시작 ===
  obs.start_stream=false → 스트림 종료도 운영자 수동(건너뜀)
  컨텐츠 팩 생성: ...

왜 3초 만에 끝났는지 알 방법이 없다. 파이썬 트레이스백은 콘솔로만
나갔고, 무인 운영에서는 그 창을 볼 사람이 없다.
"""

import logging
import types

from aist.cli import _run_broadcast_loop


class _Boom:
    async def run_one_now(self):
        raise TypeError("일부러 낸 코드 문제")


class _Fine:
    def __init__(self):
        self.ran = False

    async def run_one_now(self):
        self.ran = True


def test_예상_못_한_오류가_로그에_남고_종료코드가_1(caplog):
    with caplog.at_level(logging.ERROR, logger="aist"):
        rc = _run_broadcast_loop(_Boom(), "run_one_now", "방송")
    assert rc == 1, "실패했는데 종료코드가 0 이면 무인운영이 재시작을 안 한다"
    recs = [r for r in caplog.records if r.levelname == "ERROR"]
    assert recs, "로그에 아무 것도 안 남았다"
    assert "예상 못 한 오류" in recs[0].getMessage()
    # 코드 문제라 트레이스백이 유일한 단서다 — 같이 남겨야 한다
    assert recs[0].exc_info is not None


def test_정상_종료는_0(caplog):
    orch = _Fine()
    assert _run_broadcast_loop(orch, "run_one_now", "방송") == 0
    assert orch.ran is True
