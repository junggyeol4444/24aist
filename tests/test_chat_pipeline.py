import asyncio

from aist.chat.base import ChatMessage, ChatSource
from aist.config import BroadcastConfig, FloodHandling
from aist.chat_pipeline import ChatPipeline


class FakeBridge:
    def __init__(self):
        self.said = []
        self.proactive = 0

    async def say_to_ai(self, text, source=None):
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
        await asyncio.sleep(0.2)

    async def close(self):
        pass


def _msgs(n, sc=False):
    return [ChatMessage(author=f"u{i}", text=f"m{i}", platform="fake",
                        is_superchat=sc) for i in range(n)]


def test_forwards_all_chat_by_default():
    async def run():
        bridge = FakeBridge()
        reads = []
        cfg = BroadcastConfig(idle_proactive_speak=False)
        pipe = ChatPipeline(bridge, cfg, on_message=lambda m: reads.append(m.author))
        stop = asyncio.Event()
        task = asyncio.create_task(pipe.run(FakeSource(_msgs(5)), stop))
        await asyncio.sleep(0.1)
        stop.set()
        await asyncio.wait_for(task, timeout=2)
        return bridge.said, reads

    said, reads = asyncio.run(run())
    assert len(said) == 5          # 다 반응 (절대 원칙)
    assert len(reads) == 5         # 다 읽음


def test_flood_handling_limits_forward_but_reads_all():
    async def run():
        bridge = FakeBridge()
        reads = []
        cfg = BroadcastConfig(
            idle_proactive_speak=False,
            flood_handling=FloodHandling(enabled=True, max_per_window=1, window_sec=10),
        )
        pipe = ChatPipeline(bridge, cfg, on_message=lambda m: reads.append(m.author))
        stop = asyncio.Event()
        task = asyncio.create_task(pipe.run(FakeSource(_msgs(4)), stop))
        await asyncio.sleep(0.1)
        stop.set()
        await asyncio.wait_for(task, timeout=2)
        return bridge.said, reads

    said, reads = asyncio.run(run())
    assert len(reads) == 4         # 읽기는 전부
    assert len(said) == 1          # 폭주 구간이라 AI 발화로는 1건만
