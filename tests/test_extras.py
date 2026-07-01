"""추가 기능 테스트: chroma/recall, 영상 동출(simulcast), 셀레늄 구성."""

from aist.chat.base import ChatMessage
from aist.config import (
    MemoryConfig, ObsConfig, SimulcastConfig, SimulcastTarget,
)
from aist.memory import Memory
from aist.obs_control import ObsController


# ------------------------------ 기억 recall ------------------------------
def test_recall_keyword_fallback(tmp_path):
    m = Memory(MemoryConfig(path=str(tmp_path), backend="json"))
    m.start_session()
    m.note_chat(ChatMessage("neo", "hi", "twitch"))
    m.end_session(summary="마인크래프트 하다가 용암에 빠져 죽음")
    m.start_session()
    m.end_session(summary="노래 방송 함")

    hits = m.recall("마인크래프트")
    assert any("마인크래프트" in h for h in hits)
    assert m.recall("존재하지않는키워드") == []


# ------------------------------ 영상 동출 -------------------------------
class _FakeObsClient:
    def __init__(self):
        self.vendor_calls = []
        self.streaming = False

    def call_vendor_request(self, vendor, request, data=None):
        self.vendor_calls.append((vendor, request, data))


def _controller(sim):
    c = ObsController(ObsConfig(simulcast=sim))
    c._client = _FakeObsClient()
    return c


def test_simulcast_vendor_mode_calls_plugin():
    sim = SimulcastConfig(enabled=True, mode="vendor",
                          vendor_name="obs-multi-rtmp",
                          start_request="StartAll", stop_request="StopAll",
                          targets=[SimulcastTarget(name="youtube")])
    c = _controller(sim)
    c._simulcast(start=True)
    c._simulcast(start=False)
    calls = c._client.vendor_calls
    assert ("obs-multi-rtmp", "StartAll", None) in calls
    assert ("obs-multi-rtmp", "StopAll", None) in calls


def test_simulcast_plugin_autostart_makes_no_vendor_call():
    sim = SimulcastConfig(enabled=True, mode="plugin_autostart")
    c = _controller(sim)
    c._simulcast(start=True)
    assert c._client.vendor_calls == []      # 플러그인이 알아서 → 호출 없음


def test_simulcast_disabled_noop():
    c = _controller(SimulcastConfig(enabled=False))
    c._simulcast(start=True)
    assert c._client.vendor_calls == []


def test_simulcast_vendor_failure_is_swallowed():
    # 플러그인 없음(요청 실패)이어도 예외가 방송을 죽이지 않아야 함
    class Boom(_FakeObsClient):
        def call_vendor_request(self, *a, **k):
            raise RuntimeError("no such vendor")
    sim = SimulcastConfig(enabled=True, mode="vendor")
    c = ObsController(ObsConfig(simulcast=sim))
    c._client = Boom()
    c._simulcast(start=True)   # 예외가 밖으로 새지 않아야 함(통과하면 OK)
