"""채팅 수집 (귀) — 플랫폼 채팅을 ChatMessage 스트림으로 만든다.

핵심 방침(절대): 채팅은 기본적으로 다 읽고 다 반응한다. 여기서는 그저
'모든' 메시지를 빠짐없이 흘려보낸다. 선별/딜레이는 하지 않는다.
"""

from .base import ChatMessage, ChatSource
from .factory import make_chat_source

__all__ = ["ChatMessage", "ChatSource", "make_chat_source"]
