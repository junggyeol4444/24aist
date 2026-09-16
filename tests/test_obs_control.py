"""OBS 제어의 예외/상태 처리.

실제로 자주 일어나는 상황:
  - 운영자가 OBS 에서 직접 송출을 껐다 → 방송 종료 때 stop_stream 이
    obsws 자기 예외(OBSSDKRequestError)를 던진다.
  - 그런데 오케스트레이터는 ObsError 만 잡는다 → 종료 절차(코어 닫기,
    기록 저장, 종료 공지)가 통째로 날아간다.
여기서는 그 예외가 밖으로 새지 않는지, 새더라도 ObsError 로 바뀌는지 본다.
"""

import pytest

from aist.config import ObsConfig
from aist.obs_control import ObsController, ObsError


class _Sdk(Exception):
    """obsws-python 이 던지는 자기 예외 흉내(우리 ObsError 가 아니다)."""


class _FakeClient:
    def __init__(self, streaming=False, fail_on=(), status_raises=False):
        self.streaming = streaming
        self.fail_on = set(fail_on)
        self.status_raises = status_raises
        self.calls = []

    class _Status:
        def __init__(self, active):
            self.output_active = active

    def get_stream_status(self):
        self.calls.append("status")
        if self.status_raises:
            raise _Sdk("status 실패")
        return self._Status(self.streaming)

    def start_stream(self):
        self.calls.append("start")
        if "start" in self.fail_on:
            raise _Sdk("이미 스트리밍 중")
        self.streaming = True

    def stop_stream(self):
        self.calls.append("stop")
        if "stop" in self.fail_on:
            raise _Sdk("스트리밍 중이 아님")
        self.streaming = False


def _ctl(client):
    c = ObsController(ObsConfig())
    c._client = client
    return c


def test_stop_when_already_stopped_does_not_raise():
    # 운영자가 OBS 에서 직접 껐거나 스트림 키 오류로 자동 중단된 경우.
    cl = _FakeClient(streaming=False, fail_on=("stop",))
    _ctl(cl).stop_stream()                      # 예외가 나면 종료 절차가 깨진다
    assert "stop" not in cl.calls               # 부르지도 않는다


def test_stop_normal_path_calls_stop():
    cl = _FakeClient(streaming=True)
    _ctl(cl).stop_stream()
    assert "stop" in cl.calls
    assert cl.streaming is False


def test_start_when_already_streaming_is_skipped():
    # 하드킬 후 재시작 — OBS 는 계속 송출 중인데 다시 시작을 부른다.
    cl = _FakeClient(streaming=True, fail_on=("start",))
    _ctl(cl).start_stream()
    assert "start" not in cl.calls


def test_start_failure_becomes_obserror():
    # 상태 조회는 "안 켜짐" 인데 start 가 실패 → 호출자가 잡을 수 있는 예외로.
    cl = _FakeClient(streaming=False, fail_on=("start",))
    with pytest.raises(ObsError):
        _ctl(cl).start_stream()


def test_stop_failure_becomes_obserror():
    cl = _FakeClient(streaming=True, fail_on=("stop",))
    with pytest.raises(ObsError):
        _ctl(cl).stop_stream()


def test_status_query_failure_does_not_block_stop():
    # 상태를 모를 때(None) 는 건너뛰지 말고 그냥 시도한다.
    cl = _FakeClient(streaming=True, status_raises=True)
    assert _ctl(cl)._is_streaming() is None
    _ctl(cl).stop_stream()
    assert "stop" in cl.calls


def test_not_connected_raises_obserror():
    """켤 때는 반드시 실패로 알려야 한다 — 송출 없이 방송이 나가면 안 된다."""
    c = ObsController(ObsConfig())
    with pytest.raises(ObsError):
        c.start_stream()


def test_stop_stream_without_connection_is_not_an_error():
    """내릴 때는 조용히 넘어간다 — 끌 게 없는 걸 사고로 보고할 일이 아니다.

    OBS 가 죽어서 방송을 내리는 길에서 stop_stream 이 예외를 던지면,
    뒷정리가 "OBS 에 먼저 connect() 해야 합니다" 를 ERROR 로 찍는다.
    운영자에게는 프로그램이 잘못된 것처럼 보인다(실제 로그에서 그랬다).
    """
    c = ObsController(ObsConfig())
    c.stop_stream()


def test_start_stream_false_touches_nothing():
    cl = _FakeClient(streaming=False)
    c = ObsController(ObsConfig(start_stream=False))
    c._client = cl
    c.start_stream()
    c.stop_stream()
    assert cl.calls == []
