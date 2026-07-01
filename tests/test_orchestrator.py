import asyncio
import json
from pathlib import Path

import aist.orchestrator as orch_mod
from aist.config import (
    AnnounceConfig, BroadcastConfig, Config, EndJudgeConfig, MemoryConfig, WindDown,
)
from aist.orchestrator import Orchestrator
from aist.persona import Persona


class FakeBridge:
    last = None

    def __init__(self, cfg):
        self.events = []
        FakeBridge.last = self

    async def connect(self):
        self.events.append("connect")
        return self

    async def say_to_ai(self, text, source=None, platform=None):
        self.events.append(("say", text))

    async def proactive_speak(self):
        self.events.append("proactive")

    async def recv_loop(self, on_message=None):
        await asyncio.sleep(3600)  # 드레인 흉내 — teardown 에서 취소됨

    async def close(self):
        self.events.append("close")


class FakeObs:
    last = None

    def __init__(self, cfg):
        self.events = []
        FakeObs.last = self

    def connect(self):
        self.events.append("connect")
        return self

    def start_stream(self):
        self.events.append("start")

    def stop_stream(self):
        self.events.append("stop")

    def close(self):
        self.events.append("close")


class FakeSource:
    platform = "fake"

    async def messages(self):
        return
        yield  # async generator 표식

    async def close(self):
        pass


class FakeSourceWithMsgs:
    """메시지를 몇 개 흘린 뒤 살아있는 상태를 유지하는 채팅 소스."""
    platform = "twitch"

    def __init__(self, texts):
        self._texts = texts

    async def messages(self):
        from aist.chat.base import ChatMessage
        for i, t in enumerate(self._texts):
            yield ChatMessage(author=f"u{i}", text=t, platform=self.platform)
            await asyncio.sleep(0)
        await asyncio.sleep(5)

    async def close(self):
        pass


def _config(tmp_path):
    cfg = Config()
    cfg.platform = "twitch"
    # 즉시 종료되게: max=0, min=0, wind_down off
    cfg.end_judge = EndJudgeConfig(max_minutes=0, min_minutes=0,
                                   wind_down=WindDown(enabled=False))
    cfg.broadcast = BroadcastConfig(idle_proactive_speak=False)
    cfg.announce = AnnounceConfig()
    cfg.announce.discord.enabled = False
    cfg.announce.naver_cafe.enabled = False
    cfg.memory = MemoryConfig(path=str(tmp_path))
    cfg.logging.dir = str(tmp_path / "logs")
    cfg.logging.reports_dir = str(tmp_path / "reports")
    return cfg


def test_one_broadcast_cycle_lifecycle(tmp_path, monkeypatch):
    monkeypatch.setattr(orch_mod, "VTuberBridge", FakeBridge)
    monkeypatch.setattr(orch_mod, "ObsController", FakeObs)
    monkeypatch.setattr(orch_mod, "make_chat_source", lambda cfg: FakeSource())

    cfg = _config(tmp_path)
    orch = Orchestrator(cfg, Persona())
    asyncio.run(orch.run_one_now())

    # OBS 시작/종료, 코어 연결/종료가 일어났는지
    assert "start" in FakeObs.last.events and "stop" in FakeObs.last.events
    assert "connect" in FakeBridge.last.events and "close" in FakeBridge.last.events

    # 세션이 기억에 저장됐는지
    sessions = json.loads((Path(tmp_path) / "sessions.json").read_text(encoding="utf-8"))
    assert len(sessions) == 1
    assert sessions[0]["end"] is not None


def test_chat_actually_flows_through_orchestrator(tmp_path, monkeypatch):
    """채팅이 소스→파이프라인→브릿지→코어로 실제로 흐르는지(배선 통합 검증)."""
    monkeypatch.setattr(orch_mod, "VTuberBridge", FakeBridge)
    monkeypatch.setattr(orch_mod, "ObsController", FakeObs)
    msgs = ["안녕", "ㅋㅋㅋ", "오늘 뭐함?"]
    monkeypatch.setattr(orch_mod, "make_chat_source", lambda cfg: FakeSourceWithMsgs(msgs))

    cfg = _config(tmp_path)
    # 종료 판단이 바로 끝나지 않게(채팅이 흐를 시간 확보) 넉넉히, 종료는 stop 으로
    cfg.end_judge = EndJudgeConfig(max_minutes=180, min_minutes=0,
                                   wind_down=WindDown(enabled=False))

    orch = Orchestrator(cfg, Persona())

    async def run():
        task = asyncio.create_task(orch.run_one_now())
        await asyncio.sleep(0.2)      # 채팅이 흐를 시간
        orch.request_stop()
        await asyncio.wait_for(task, timeout=5)

    asyncio.run(run())

    said = [e[1] for e in FakeBridge.last.events
            if isinstance(e, tuple) and e[0] == "say"]
    assert said == msgs                       # 다 반응(절대 원칙) + 순서 유지
    sessions = json.loads((Path(tmp_path) / "sessions.json").read_text(encoding="utf-8"))
    assert len(sessions[0]["viewers"]) == 3   # 다 읽음(기억에 반영)

    # 트랜스크립트가 채팅을 기록했는지
    tfiles = list((Path(tmp_path) / "logs" / "transcripts").glob("*.jsonl"))
    assert len(tfiles) == 1
    content = tfiles[0].read_text(encoding="utf-8")
    assert "ㅋㅋㅋ" in content

    # 방송 후 리포트가 자동 생성됐는지 (다시보기 학습)
    reports = list((Path(tmp_path) / "reports").glob("*.md"))
    assert len(reports) == 1
    assert "시청자(채팅 기준): 3명" in reports[0].read_text(encoding="utf-8")
