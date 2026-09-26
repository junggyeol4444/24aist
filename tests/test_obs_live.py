"""진짜 obsws-python 클라이언트로 OBS 제어 경로를 돌려본다.

가짜 클라이언트 객체로만 테스트하면 "우리가 부르는 메서드 이름이 맞는지",
"응답 모양이 맞는지", "라이브러리가 던지는 예외를 우리가 제대로 감싸는지"
를 하나도 검증하지 못한다. 그래서 obs-websocket v5 규격대로 응답하는 작은
서버를 띄우고, 실제 클라이언트로 붙여서 확인한다.
(obsws-python / websockets 가 없는 환경에서는 건너뛴다)
"""

import asyncio
import base64
import hashlib
import json
import socket
import threading

import pytest

pytest.importorskip("obsws_python")
pytest.importorskip("websockets")

from aist.config import ObsConfig  # noqa: E402
from aist.obs_control import ObsController, ObsError  # noqa: E402


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class FakeObs:
    """obs-websocket v5 서버 흉내."""

    def __init__(self, password: str = "", fail: tuple = ()):
        self.password = password
        self.fail = set(fail)
        self.port = _free_port()
        self.streaming = False
        self.scene = ""
        self.calls = []
        self._loop = None
        self._thread = None
        self._stop = None
        self._ready = threading.Event()

    # --- 서버 ---
    def _auth(self, salt, challenge):
        secret = base64.b64encode(
            hashlib.sha256((self.password + salt).encode()).digest())
        return base64.b64encode(
            hashlib.sha256(secret + challenge.encode()).digest()).decode()

    async def _handler(self, ws):
        import websockets  # noqa: F401
        salt, challenge = "saltsalt", "challenge1"
        hello = {"op": 0, "d": {"obsWebSocketVersion": "5.1.0", "rpcVersion": 1}}
        if self.password:
            hello["d"]["authentication"] = {"challenge": challenge, "salt": salt}
        await ws.send(json.dumps(hello))
        ident = json.loads(await ws.recv())
        if self.password:
            if (ident.get("d") or {}).get("authentication") != self._auth(salt, challenge):
                await ws.close(code=4009, reason="Authentication failed")
                return
        await ws.send(json.dumps({"op": 2, "d": {"negotiatedRpcVersion": 1}}))
        async for raw in ws:
            msg = json.loads(raw)
            if msg.get("op") != 6:
                continue
            d = msg["d"]
            rtype, rid = d["requestType"], d["requestId"]
            data = d.get("requestData") or {}
            self.calls.append(rtype)
            ok, code, resp = True, 100, {}
            if rtype in self.fail:
                ok, code = False, 604
            elif rtype == "GetStreamStatus":
                resp = {"outputActive": self.streaming, "outputReconnecting": False,
                        "outputTimecode": "00:00:00.000", "outputDuration": 0,
                        "outputCongestion": 0.0, "outputBytes": 0,
                        "outputSkippedFrames": 0, "outputTotalFrames": 0}
            elif rtype == "StartStream":
                self.streaming = True
            elif rtype == "StopStream":
                self.streaming = False
            elif rtype == "SetCurrentProgramScene":
                self.scene = data.get("sceneName", "")
            await ws.send(json.dumps({"op": 7, "d": {
                "requestType": rtype, "requestId": rid,
                "requestStatus": {"result": ok, "code": code},
                "responseData": resp}}))

    def _run(self):
        import websockets

        async def main():
            self._stop = asyncio.Event()
            async with websockets.serve(self._handler, "127.0.0.1", self.port):
                self._ready.set()
                await self._stop.wait()

        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(main())
        finally:
            self._loop.close()

    def __enter__(self):
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        assert self._ready.wait(10), "가짜 OBS 서버가 안 떴습니다"
        return self

    def __exit__(self, *exc):
        # 깔끔하게 내린다 — 루프만 멈추면 "coroutine was never awaited" 경고가
        # 남아서 진짜 경고를 가린다.
        if self._loop is not None and self._stop is not None:
            self._loop.call_soon_threadsafe(self._stop.set)
        if self._thread is not None:
            self._thread.join(timeout=5)
        return False

    def cfg(self, **kw) -> ObsConfig:
        return ObsConfig(host="127.0.0.1", port=self.port,
                         password=self.password, start_stream=True, **kw)


def test_start_stop_cycle_with_real_client():
    with FakeObs() as obs:
        c = ObsController(obs.cfg()).connect()
        c.start_stream()
        assert obs.streaming is True
        c.set_scene("방송중")
        assert obs.scene == "방송중"
        c.stop_stream()
        assert obs.streaming is False
        c.close()


def test_double_start_and_double_stop_are_skipped():
    """운영자가 두 번 눌러도, 하드킬 후 재시작이어도 터지면 안 된다."""
    with FakeObs() as obs:
        c = ObsController(obs.cfg()).connect()
        c.start_stream()
        obs.calls.clear()
        c.start_stream()                       # 이미 송출 중
        assert "StartStream" not in obs.calls
        c.stop_stream()
        obs.calls.clear()
        c.stop_stream()                        # 이미 꺼짐
        assert "StopStream" not in obs.calls
        c.close()


def test_request_failure_becomes_obserror():
    """라이브러리 예외(OBSSDKRequestError)가 그대로 새면 방송 절차가 깨진다."""
    with FakeObs(fail=("StartStream",)) as obs:
        c = ObsController(obs.cfg()).connect()
        with pytest.raises(ObsError):
            c.start_stream()
        c.close()


def test_wrong_password_says_what_to_fix():
    with FakeObs(password="비밀번호123") as obs:
        cfg = obs.cfg()
        cfg.password = "틀린비번"
        with pytest.raises(ObsError) as e:
            ObsController(cfg).connect()
        assert "비밀번호" in str(e.value)


def test_correct_password_connects():
    with FakeObs(password="비밀번호123") as obs:
        c = ObsController(obs.cfg()).connect()
        c.start_stream()
        c.stop_stream()
        c.close()
