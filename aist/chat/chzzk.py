"""치지직(chzzk) 채팅 리더 — 통합 지점(아직 미구현).

치지직은 공식 공개 채팅 API 가 없어, 비공식 채팅 WebSocket(세션 키
발급 → 채팅 서버 연결)을 직접 다뤄야 한다. 약관/안정성 확인이 필요하고
방식이 자주 바뀌므로, 플랫폼을 치지직으로 확정한 뒤 이 파일을 채운다.

채우는 방법(요약):
  1) https://api.chzzk.naver.com/polling/v2/channels/{channel_id}/live-status
     로 chatChannelId 획득
  2) 액세스 토큰 발급(GET .../chats/access-token?chatChannelId=...&chatType=STREAMING)
  3) wss 채팅 서버에 연결 → CONNECT 메시지(bdy 에 accTkn 등) → 채팅 수신
  4) 수신 메시지를 ChatMessage 로 변환해 yield (다 흘려보냄)

구현 시에도 "다 읽고 다 반응" 원칙을 지켜 메시지를 선별하지 않는다.
"""

from typing import AsyncIterator

from .base import ChatMessage, ChatSource


class ChzzkChat(ChatSource):
    platform = "chzzk"

    def __init__(self, channel_id: str):
        self.channel_id = channel_id

    async def messages(self) -> AsyncIterator[ChatMessage]:
        raise NotImplementedError(
            "치지직 채팅 연동은 아직 구현되지 않았습니다. "
            "aist/chat/chzzk.py 상단 주석의 절차대로 채워 넣으세요. "
            "(트위치/유튜브는 바로 사용 가능합니다.)"
        )
        yield  # pragma: no cover  (async generator 로 만들기 위한 표시)
