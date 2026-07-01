"""공지 채널 공통 인터페이스."""

import abc


class Announcer(abc.ABC):
    name: str = "base"

    @abc.abstractmethod
    async def post(self, text: str, *, title: str = "") -> bool:
        """공지를 게시한다. 성공하면 True. 실패는 예외 대신 False + 로그."""
        ...

    async def close(self) -> None:
        return None
