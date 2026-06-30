import asyncio
import json

import pytest

from aist.chat.base import ChatMessage, ChatSource
from aist.chat.factory import make_chat_source, make_single_source
from aist.chat.multi import MultiChatSource
from aist.config import Config


# --------------------------- 파서 단위 테스트 ---------------------------
def test_kick_parse_event():
    from aist.chat.kick import _parse_chat_event
    out = _parse_chat_event(json.dumps({"content": "hi", "sender": {"username": "Neo"}}))
    assert out == ("Neo", "hi")
    assert _parse_chat_event("not-json") is None


def test_chzzk_parse_chat_and_donation():
    from aist.chat.chzzk import _parse_chat_bdy
    chat = {"cmd": 93101, "bdy": [{"profile": json.dumps({"nickname": "별님"}), "msg": "안녕"}]}
    assert _parse_chat_bdy(chat) == [("별님", "안녕", False, "")]
    dono = {"cmd": 93102, "bdy": [{"profile": None, "msg": "감사", "extras": json.dumps({"payAmount": 1000})}]}
    nick, text, is_dono, amount = _parse_chat_bdy(dono)[0]
    assert is_dono is True and amount == "1000" and text == "감사"


def test_soop_packet_roundtrip():
    from aist.chat.soop import _parse_packet, _packet, F
    body = f"{F}안녕{F}시청자A{F}"
    frame = _packet(5, body)[2:]  # ESC 제거
    assert _parse_packet(frame) == ("시청자A", "안녕")
    # 채팅이 아닌 svc 는 None
    assert _parse_packet(_packet(1, body)[2:]) is None


# --------------------------- 팩토리 / 동출 ---------------------------
def _cfg(**raw):
    # 최소 Config 를 직접 만든다(파일 없이)
    from aist.config import ChatConfig, TwitchChatCfg, ChzzkChatCfg, KickChatCfg
    c = Config()
    c.chat = ChatConfig(
        twitch=TwitchChatCfg(channel="a"),
        chzzk=ChzzkChatCfg(channel_id="b"),
        kick=KickChatCfg(channel="c"),
    )
    for k, v in raw.items():
        setattr(c, k, v)
    return c


def test_factory_single_source():
    c = _cfg(platform="kick")
    src = make_chat_source(c)
    assert src.platform == "kick"
    assert not isinstance(src, MultiChatSource)


def test_factory_multi_source_for_simulcast():
    c = _cfg(platforms=["twitch", "chzzk", "kick"])
    src = make_chat_source(c)
    assert isinstance(src, MultiChatSource)
    assert [s.platform for s in src.sources] == ["twitch", "chzzk", "kick"]


def test_factory_unknown_platform():
    with pytest.raises(ValueError):
        make_single_source("myspace", Config())


# --------------------------- MultiChatSource 병합 ---------------------------
class _FakeSrc(ChatSource):
    def __init__(self, name, msgs):
        self.platform = name
        self._msgs = msgs

    async def messages(self):
        for m in self._msgs:
            yield m
            await asyncio.sleep(0)
        await asyncio.sleep(5)  # 소스가 살아있는 상태 유지

    async def close(self):
        pass


def test_multi_merges_all_platforms():
    async def run():
        a = _FakeSrc("twitch", [ChatMessage("u1", "a", "twitch")])
        b = _FakeSrc("chzzk", [ChatMessage("u2", "b", "chzzk")])
        multi = MultiChatSource([a, b])
        got = []

        async def consume():
            async for m in multi.messages():
                got.append((m.platform, m.text))
                if len(got) >= 2:
                    break

        await asyncio.wait_for(consume(), timeout=2)
        await multi.close()
        return got

    got = asyncio.run(run())
    assert set(got) == {("twitch", "a"), ("chzzk", "b")}


# --------------------------- TwitCasting 폴링 중복제거 ---------------------------
def test_twitcasting_suppresses_first_poll_then_emits_new():
    from aist.chat.twitcasting import TwitcastingChat

    async def run():
        tc = TwitcastingChat("user", "token", poll_interval=0.01)
        state = {"n": 0}
        seqs = [
            [{"id": "1", "message": "old", "from_user": {"name": "a"}}],
            [{"id": "2", "message": "new1", "from_user": {"name": "b"}},
             {"id": "1", "message": "old", "from_user": {"name": "a"}}],
        ]
        tc._current_movie_id = lambda: "m1"

        def fetch(mid):
            i = min(state["n"], len(seqs) - 1)
            state["n"] += 1
            return seqs[i]
        tc._fetch_comments = fetch

        got = []

        async def consume():
            async for m in tc.messages():
                got.append(m.text)
                break

        await asyncio.wait_for(consume(), timeout=2)
        await tc.close()
        return got

    assert asyncio.run(run()) == ["new1"]
