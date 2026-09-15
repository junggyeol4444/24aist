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

    @abc.abstractmethod
    async def messages(self) -> AsyncIterator[ChatMessage]:
        ...

    async def close(self) -> None:
        return None

    async def probe(self) -> ProbeResult:
        """가벼운 연결/도달 점검(aist doctor 용).

        기본은 구성만 확인. 도달성 확인이 싼 플랫폼은 하위 클래스에서 override.
        """
        return probe_ok("구성됨(실제 연결은 broadcast-now 에서 확인)")
