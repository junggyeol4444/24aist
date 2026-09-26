"""채팅이 0줄일 때, "아무도 안 왔다" 와 "아예 못 붙었다" 는 다르다.

채널 ID 를 틀린 채로 3분 방송을 실제로 돌려봤다. 리포트에는
"시청자(채팅 기준): 0명" 만 적혔다. 새로 시작한 방송인은 그걸 보고
"아무도 안 오네" 라고 읽는다 — 사실은 채팅이 아예 안 들어온 것이고,
고쳐야 할 건 채널 ID 다. 완전히 다른 얘기인데 리포트가 같게 보였다.
"""

import asyncio

from aist.chat.base import ChatSource, RetryLog
from aist.chat.multi import MultiChatSource
from aist.chat.rehearsal import RehearsalChat
from aist.report import _EVENT_LABEL, _SERIOUS, _trouble_lines


class _Src(ChatSource):
    platform = "가짜"

    async def messages(self):
        return
        yield  # pragma: no cover


def test_붙은_적_없으면_그대로_남는다():
    s = _Src()
    assert s.connected_once is False
    assert s.last_error == ""


def test_실패_사유를_들고_있는다():
    s = _Src()
    log_ = RetryLog(__import__("logging").getLogger("t"), "가짜")
    s.wait_after(log_, ConnectionError("Tunnel connection failed: 403 Forbidden"))
    assert "403" in s.last_error
    assert "ConnectionError" in s.last_error


def test_리허설은_항상_붙은_것으로_본다():
    src = RehearsalChat()

    async def go():
        async for _ in src.messages():
            return

    asyncio.run(asyncio.wait_for(go(), 10))
    assert src.connected_once is True


def test_동출은_하나라도_붙으면_붙은_것():
    a, b = _Src(), _Src()
    m = MultiChatSource([a, b])
    assert m.connected_once is False
    b.connected_once = True
    assert m.connected_once is True


def test_동출은_모든_플랫폼의_사유를_모아_보여준다():
    a, b = _Src(), _Src()
    a.platform, b.platform = "치지직", "트위치"
    a.last_error = "403"
    b.last_error = "타임아웃"
    m = MultiChatSource([a, b])
    assert "치지직: 403" in m.last_error and "트위치: 타임아웃" in m.last_error


def test_리포트가_사고로_취급한다():
    assert "chat_never_connected" in _SERIOUS
    assert "chat_never_connected" in _EVENT_LABEL
    out = _trouble_lines([{"kind": "chat_never_connected"}])
    assert out and "시청자가 없었던 게 아님" in out[0]
