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


def test_rehearsal_uses_the_same_lock_as_a_real_broadcast(tmp_path, monkeypatch, capsys):
    """리허설이 방송 중에 끼어들면 안 된다.

    리허설은 송출·공지를 안 하니 안전해 보이지만, 코어에는 진짜로 붙어서
    가짜 채팅을 밀어 넣는다. 실제로 방송 중에 돌려보니 같은 구간의 발화
    수가 채팅 15개에 31회 — 두 배가 됐다. 시청자 화면에서는 방송인이
    보이지도 않는 시청자에게 떠드는 것으로 보인다.
    """
    from aist.cli import _acquire_single
    from aist.config import Config, SafetyConfig

    cfg = Config(safety=SafetyConfig(stop_flag_path=str(tmp_path / "STOP")))
    live = _acquire_single(cfg)              # 방송이 먼저 잡고
    assert live is not None
    try:
        assert _acquire_single(cfg, rehearsal=True) is None
        out = capsys.readouterr().out
        assert "리허설" in out and "방송이 끝난 뒤" in out
    finally:
        live.release()
    # 방송이 끝나면 리허설은 정상으로 돌아야 한다
    reh = _acquire_single(cfg, rehearsal=True)
    assert reh is not None
    reh.release()


def test_only_broadcast_commands_write_the_broadcast_log(tmp_path, monkeypatch):
    """점검·미리보기 명령이 방송 로그 파일에 끼어들면 안 된다.

    방송 중에 aist check 를 돌렸더니 그 줄("코어 연결됨")이 방송 로그
    한가운데에 남았다. 나중에 방송 기록을 되짚을 때 무슨 일이 있었는지
    알 수 없게 된다.
    """
    import logging
    from logging.handlers import RotatingFileHandler

    from aist.cli import _load

    cfg_path = tmp_path / "c.yaml"
    cfg_path.write_text(f'logging:\n  dir: "{tmp_path.as_posix()}/logs"\n',
                        encoding="utf-8")

    class _Args:
        config = str(cfg_path)
        persona = str(tmp_path / "없는파일.yaml")

    root = logging.getLogger()
    for h in list(root.handlers):
        if isinstance(h, RotatingFileHandler):
            root.removeHandler(h)

    def file_handlers():
        return [h for h in logging.getLogger().handlers
                if isinstance(h, RotatingFileHandler)]

    _load(_Args())                      # 점검류 — 파일 로그 없음
    assert file_handlers() == []
    _load(_Args(), file_log=True)       # 방송 — 파일 로그 있음
    assert len(file_handlers()) == 1
    for h in file_handlers():
        logging.getLogger().removeHandler(h)
        h.close()
