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
