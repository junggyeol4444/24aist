"""채팅 공통 인터페이스."""

import abc
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import AsyncIterator, Optional


@dataclass
class ChatMessage:
    author: str
    text: str
    platform: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    is_superchat: bool = False
    amount: str = ""          # 슈퍼챗 금액 표기(있으면)
    raw: Optional[object] = None
    # 게임 안에서 온 말인지(마인크래프트 서버의 다른 플레이어 등).
    # 시청자 수·단골 집계에 섞으면 안 된다 — 방송을 보고 있는 사람이 아니다.
    from_game: bool = False


@dataclass
class ProbeResult:
    """점검 결과. 단순 문자열이면 실패도 [OK] 로 찍혀 운영자를 속인다.

    level:
      ok   — 지금 바로 쓸 수 있음
      warn — 설정은 맞는데 지금은 아님(예: 아직 방송 전이라 온에어 아님)
      fail — 고쳐야 함(토큰/아이디/네트워크)
    """
    level: str = "ok"          # ok | warn | fail
    detail: str = ""

    def __str__(self) -> str:  # 로그/출력에 그대로 쓸 수 있게
        return self.detail


def probe_ok(detail: str) -> ProbeResult:
    return ProbeResult("ok", detail)


def probe_warn(detail: str) -> ProbeResult:
    return ProbeResult("warn", detail)


def probe_fail(detail: str) -> ProbeResult:
    return ProbeResult("fail", detail)


class ChatSource(abc.ABC):
    """플랫폼별 채팅 리더의 공통 인터페이스.

    messages() 는 들어오는 모든 채팅을 빠짐없이 yield 하는 비동기
    제너레이터다. 구현체는 채팅을 임의로 버리거나 지연시키지 않는다.
    """

    platform: str = "base"
    # 이 방송에서 한 번이라도 실제로 붙었는지. 안 붙었으면 "아무도 안 왔다"
    # 가 아니라 "채팅이 아예 안 들어왔다" 다 — 운영자에게 완전히 다른 얘기다.
    connected_once: bool = False
    # 마지막 실패 사유(못 붙은 채로 끝났을 때 리포트에 적어준다).
    last_error: str = ""
    # 재시도해도 절대 안 고쳐지는 이유로 포기했을 때, 그 이유를 여기 남긴다.
    # (예: 패키지 미설치) 오케스트레이터는 이게 차 있으면 다시 만들지
    # 않는다 — 안 그러면 몇 초마다 같은 실패를 영원히 반복한다.
    fatal: str = ""

    @abc.abstractmethod
    async def messages(self) -> AsyncIterator[ChatMessage]:
        ...

    def wait_after(self, retry: "RetryLog", err: Exception) -> float:
        """실패 사유를 남기고, 다음 시도까지 기다릴 초를 돌려준다.

        사유를 들고 있어야 방송이 끝난 뒤 "아무도 안 왔다" 와 "아예 못
        붙었다" 를 구분해서 알려줄 수 있다.
        """
        self.last_error = f"{type(err).__name__}: {err}"
        return retry.failure(err)

    async def close(self) -> None:
        return None

    async def probe(self) -> ProbeResult:
        """가벼운 연결/도달 점검(aist doctor 용).

        기본은 구성만 확인. 도달성 확인이 싼 플랫폼은 하위 클래스에서 override.
        """
        return probe_ok("구성됨(실제 연결은 broadcast-now 에서 확인)")


class RetryLog:
    """같은 실패가 반복될 때 로그와 재시도 간격을 알아서 줄인다.

    플랫폼이 점검 중이거나 채널 ID 가 틀리면 연결은 영영 안 된다. 그런데
    5초마다 같은 ERROR 를 찍으면 3시간 방송에서 같은 줄이 2천 개 넘게
    쌓이고, 회전 로그가 밀려 정작 필요한 기록이 사라진다. 플랫폼 API 를
    5초마다 3시간 두드리는 것도 좋은 일이 아니다(차단당한다).

    - 간격은 base 에서 시작해 두 배씩, cap 까지만 늘린다.
    - 같은 사유가 이어지면 1·3·10회째, 그 뒤로는 20회마다만 남긴다.
    - 사유가 바뀌면 처음부터 다시 센다(새 정보니까 바로 알린다).
    """

    def __init__(self, log, what: str, base: float = 5.0, cap: float = 60.0):
        self._log = log
        self._what = what
        self._base = max(0.5, base)
        self._cap = max(self._base, cap)
        self._n = 0
        self._last = None

    @property
    def last_reason(self) -> str:
        return self._last or ""

    def failure(self, err: Exception) -> float:
        """실패 한 번을 기록하고, 다음 시도까지 기다릴 초를 돌려준다."""
        reason = f"{type(err).__name__}: {err}"
        if reason != self._last:
            self._last, self._n = reason, 0
        self._n += 1
        wait = min(self._cap, self._base * (2 ** (self._n - 1)))
        if self._n in (1, 3, 10) or self._n % 20 == 0:
            extra = f" — 같은 오류 {self._n}번째" if self._n > 1 else ""
            self._log.error("%s: %s (%.0f초 후 재시도%s)",
                            self._what, err, wait, extra)
        return wait

    def success(self) -> None:
        self._n = 0
        self._last = None


def import_problem(err: Exception, package: str) -> Optional[str]:
    """재시도해도 절대 안 고쳐지는 실패(패키지 미설치)인지.

    문제면 운영자가 할 일이 적힌 문장을, 아니면 None 을 돌려준다.
    """
    if not isinstance(err, ImportError):
        return None
    return (f"{package} 가 설치되어 있지 않습니다 — `pip install {package}`. "
            "다시 시도해도 고쳐지지 않으므로 이 채팅은 포기합니다 "
            "(윈도우: windows\\설치.bat).")
