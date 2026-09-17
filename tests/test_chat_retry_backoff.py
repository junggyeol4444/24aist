"""플랫폼이 죽어 있을 때 같은 오류를 5초마다 영원히 찍던 문제.

실제 실행에서 확인: 채팅 소스가 못 붙는 상태로 방송을 돌리니 5초마다
같은 ERROR 한 줄이 계속 쌓였다. 3시간 방송이면 2천 줄이 넘고, 회전
로그가 밀려 정작 필요한 기록이 사라진다. 플랫폼 API 를 5초마다 3시간
두드리는 것도 차단당할 짓이다.
"""

import logging

from aist.chat.base import RetryLog, import_problem


def test_backoff_grows_and_is_capped():
    r = RetryLog(logging.getLogger("t"), "테스트", base=5.0, cap=60.0)
    waits = [r.failure(RuntimeError("같은 사유")) for _ in range(8)]
    assert waits[:4] == [5.0, 10.0, 20.0, 40.0]
    assert all(w == 60.0 for w in waits[4:])


def test_repeated_same_error_is_logged_sparsely(caplog):
    r = RetryLog(logging.getLogger("t"), "테스트", base=1.0, cap=1.0)
    with caplog.at_level(logging.ERROR, logger="t"):
        for _ in range(40):
            r.failure(RuntimeError("같은 사유"))
    # 1·3·10·20·40 회째만 — 40줄이 아니라 다섯 줄
    assert len(caplog.records) == 5


def test_new_reason_is_reported_immediately(caplog):
    r = RetryLog(logging.getLogger("t"), "테스트", base=1.0, cap=1.0)
    with caplog.at_level(logging.ERROR, logger="t"):
        for _ in range(5):
            r.failure(RuntimeError("사유 A"))
        r.failure(RuntimeError("사유 B"))       # 새 정보 → 바로 알린다
    assert "사유 B" in caplog.records[-1].getMessage()


def test_success_resets_backoff():
    r = RetryLog(logging.getLogger("t"), "테스트", base=5.0, cap=60.0)
    for _ in range(5):
        r.failure(RuntimeError("x"))
    r.success()
    assert r.failure(RuntimeError("x")) == 5.0


def test_missing_package_is_not_worth_retrying():
    """패키지가 없으면 재시도해도 절대 안 고쳐진다 — 포기하고 알려야 한다."""
    msg = import_problem(ModuleNotFoundError("No module named 'requests'"), "requests")
    assert msg and "pip install requests" in msg
    assert import_problem(TimeoutError("네트워크"), "requests") is None


# --------- 오케스트레이터 쪽: 다시 붙이기를 몇 초마다 영원히 하지 않는다 -----
def _orc():
    from aist.config import Config
    from aist.orchestrator import Orchestrator
    from aist.persona import Persona
    o = Orchestrator(Config(), Persona())
    return o


def test_restart_gives_up_on_unfixable_source(caplog):
    """패키지가 없어서 죽은 채팅을 8초마다 다시 만들면 안 된다.

    실제 실행에서 90초 동안 로그가 49줄 쌓였다 — "끊겼습니다 / 복구됨 /
    소스가 끝났습니다" 가 끝없이 반복됐다.
    """
    import asyncio

    class _Dead:
        platform = "chzzk"
        fatal = "requests 가 설치되어 있지 않습니다"

    o = _orc()
    o._chat_source = _Dead()
    with caplog.at_level(logging.ERROR, logger="aist.orchestrator"):
        for _ in range(5):
            assert asyncio.run(o._restart_chat(o.cfg, None, None, None)) is None
    # 다섯 번 불러도 한 번만 알린다
    assert len(caplog.records) == 1
    assert "혼잣말" in caplog.records[0].getMessage()


def test_restart_backs_off_instead_of_hammering():
    """붙였다 끊겼다를 반복하면 간격이 늘어야 한다."""
    import asyncio

    o = _orc()
    waits = []

    async def fake_sleep(sec):
        waits.append(sec)

    o._sleep_or_stop = fake_sleep
    o._stop.set()          # 잠든 뒤 바로 빠져나오게
    for _ in range(4):
        asyncio.run(o._restart_chat(o.cfg, None, None, None))
    assert waits == [3.0, 6.0, 12.0, 24.0]
