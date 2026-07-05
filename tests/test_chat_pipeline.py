import asyncio

from aist.chat.base import ChatMessage, ChatSource
from aist.config import BroadcastConfig, FloodHandling
from aist.chat_pipeline import ChatPipeline


class FakeBridge:
    def __init__(self):
        self.said = []
        self.proactive = 0

    async def say_to_ai(self, text, source=None, platform=None):
        self.said.append((source, text))

    async def proactive_speak(self):
        self.proactive += 1


class FakeSource(ChatSource):
    platform = "fake"

    def __init__(self, messages):
        self._messages = messages

    async def messages(self):
        for m in self._messages:
            yield m
            await asyncio.sleep(0)
        # 끝나지 않게 잠깐 대기(소비 완료 후 stop 설정될 시간)
        await asyncio.sleep(5)

    async def close(self):
        pass


def _msgs(n, sc=False):
    return [ChatMessage(author=f"u{i}", text=f"m{i}", platform="fake",
                        is_superchat=sc) for i in range(n)]


def _all_texts(said):
    return "\n".join(t for (_s, t) in said)


def test_all_chat_reaches_ai():
    """다 반응(절대 원칙): 채팅 5개가 전부 AI 에게 전달된다.

    '입 하나' 모델이라 첫 개는 즉시, 나머지는 말 끝난 뒤 묶여 전달될 수
    있지만 하나도 버려지지 않는다.
    """
    async def run():
        bridge = FakeBridge()
        reads = []
        cfg = BroadcastConfig(idle_proactive_speak=False, core_busy_timeout_sec=0)
        pipe = ChatPipeline(bridge, cfg, on_message=lambda m: reads.append(m.author))
        stop = asyncio.Event()
        task = asyncio.create_task(pipe.run(FakeSource(_msgs(5)), stop))
        await asyncio.sleep(0.9)   # pacer(0.3s)가 잔여분 흘려보낼 시간
        stop.set()
        await asyncio.wait_for(task, timeout=2)
        return bridge.said, reads

    said, reads = asyncio.run(run())
    joined = _all_texts(said)
    for i in range(5):
        assert f"m{i}" in joined          # 다 반응 (절대 원칙)
    assert len(reads) == 5                # 다 읽음


def test_one_mouth_buffers_while_speaking_and_resumes():
    """말하는 중엔 쌓고, 말 끝(chain-end)나는 순간 전부 이어받는다."""
    async def run():
        bridge = FakeBridge()
        cfg = BroadcastConfig(idle_proactive_speak=False)   # timeout 기본(90s)
        pipe = ChatPipeline(bridge, cfg)
        stop = asyncio.Event()
        task = asyncio.create_task(pipe.run(FakeSource(_msgs(3)), stop))
        await asyncio.sleep(0.5)
        # m0 은 즉시 나가고 busy 잠김 → m1, m2 는 쌓여 있어야 함
        first_said = list(bridge.said)
        pending_before = pipe.has_pending()
        # 코어가 말 끝 신호를 보냄 → pacer 가 쌓인 걸 한 호흡으로 전달
        pipe.on_core_message({"type": "control", "text": "conversation-chain-end"})
        await asyncio.sleep(0.7)
        stop.set()
        await asyncio.wait_for(task, timeout=2)
        return first_said, pending_before, bridge.said

    first_said, pending_before, said = asyncio.run(run())
    assert len(first_said) == 1 and "m0" in first_said[0][1]
    assert pending_before is True
    # 말 끝난 뒤 m1+m2 가 '한 번에' 이어받아짐 (버려진 것 없음, 순서 유지)
    assert len(said) == 2
    batch = said[1][1]
    assert "m1" in batch and "m2" in batch
    assert batch.index("m1") < batch.index("m2")
    # 쌓인 채팅은 '훑어보듯' 반응하라는 귓속말이 함께 감(하나하나 다 답 X)
    assert "훑어보듯" in batch


def test_flood_handling_limits_forward_but_reads_all():
    async def run():
        bridge = FakeBridge()
        reads = []
        cfg = BroadcastConfig(
            idle_proactive_speak=False, core_busy_timeout_sec=0,
            flood_handling=FloodHandling(enabled=True, max_per_window=1, window_sec=10),
        )
        pipe = ChatPipeline(bridge, cfg, on_message=lambda m: reads.append(m.author))
        stop = asyncio.Event()
        task = asyncio.create_task(pipe.run(FakeSource(_msgs(4)), stop))
        await asyncio.sleep(0.6)
        stop.set()
        await asyncio.wait_for(task, timeout=2)
        return bridge.said, reads

    said, reads = asyncio.run(run())
    assert len(reads) == 4         # 읽기는 전부
    assert len(said) == 1          # 폭주 구간이라 AI 발화로는 1건만


def test_idle_gap_is_bounded_and_reset():
    """진행자 혼잣말: 다음 말 걸 공백이 min~max 안에 있고, 채팅/발화로 리셋."""
    import time
    cfg = BroadcastConfig(idle_gap_min_sec=6, idle_gap_max_sec=15)
    pipe = ChatPipeline(FakeBridge(), cfg)
    gap = pipe._next_idle_at - time.monotonic()
    assert 6 <= gap <= 15 + 0.05
    # 말하면(_mark_busy) 공백이 다시 잡힌다
    pipe._next_idle_at = 0.0
    pipe._mark_busy()
    assert pipe._next_idle_at > time.monotonic()


def test_idle_speak_fires_when_quiet():
    """짧은 공백만 생겨도 진행자처럼 말을 잇는다(채팅 없어도 방송 끌기)."""
    async def run():
        bridge = FakeBridge()
        # 즉시 말 걸도록 gap 을 0 근처로
        cfg = BroadcastConfig(idle_gap_min_sec=2, idle_gap_max_sec=2)
        pipe = ChatPipeline(bridge, cfg)
        pipe._next_idle_at = 0.0          # 지금 바로 말할 때가 됨
        await pipe._maybe_idle_speak()
        return bridge.proactive

    assert asyncio.run(run()) == 1
