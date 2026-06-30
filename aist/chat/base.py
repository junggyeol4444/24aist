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
