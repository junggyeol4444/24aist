"""웹UI 가 코어에서 떨어졌을 때 OBS 브라우저 소스를 직접 새로고침하는지.

로그로 "새로고침하세요" 라고 부탁하는 건 무인 운영에서 아무 소용이 없다.
실제로 코어를 죽였다 살린 실행에서, 우리 쪽은 "재연결 성공" 인데 그 뒤
발화가 계속 걸리고 화면은 조용한 상태가 재현됐다.
"""

from aist.config import ObsConfig
from aist.obs_control import ObsController


class _FakeClient:
    """obs-websocket 응답 모양(obsws-python 이 돌려주는 객체)을 흉내낸다."""

    def __init__(self):
        self.pressed = []

    class _R:
        def __init__(self, **kw):
            self.__dict__.update(kw)

    def get_input_list(self, kind=None):
        return self._R(inputs=[
            {"inputName": "웹UI", "inputKind": "browser_source"},
            {"inputName": "알림창", "inputKind": "browser_source"},
            {"inputName": "마이크", "inputKind": "wasapi_input_capture"},
        ])

    def get_input_settings(self, name):
        urls = {"웹UI": "http://127.0.0.1:12393/",
                "알림창": "https://alerts.example.com/w/abc"}
        return self._R(input_settings={"url": urls[name]})

    def press_input_properties_button(self, input_name, prop_name):
        self.pressed.append((input_name, prop_name))


def _controller():
    c = ObsController(ObsConfig())
    c._client = _FakeClient()
    return c


def test_코어를_가리키는_브라우저_소스만_새로고침한다():
    c = _controller()
    assert c.refresh_browser_sources("127.0.0.1:12393") == 1
    # 알림창·마이크는 건드리지 않는다(괜히 화면이 깜빡인다)
    assert c._client.pressed == [("웹UI", "refreshnocache")]


def test_주소가_안_맞으면_아무것도_안_누른다():
    c = _controller()
    assert c.refresh_browser_sources("127.0.0.1:9999") == 0
    assert c._client.pressed == []


def test_OBS_에_안_붙어_있으면_조용히_넘어간다():
    c = ObsController(ObsConfig())
    assert c.connected() is False
    assert c.refresh_browser_sources("127.0.0.1:12393") == 0


def test_버튼이_없는_OBS_버전이어도_방송을_안_깬다():
    c = _controller()

    def boom(input_name, prop_name):
        raise RuntimeError("이 OBS 버전엔 그 버튼이 없다")

    c._client.press_input_properties_button = boom
    assert c.refresh_browser_sources("127.0.0.1:12393") == 0


def test_방송_시작_전_새로고침은_사고로_세지_않는다(tmp_path):
    """코어가 새로 뜬 뒤 방송을 켜면 웹UI 는 끊긴 채다(진짜 웹UI 로 확인).

    그래서 방송 시작 때마다 새로 읽히는데, 이건 계획된 일이라 리포트의
    사고 목록에 오르거나 사고 때 쓸 새로고침 횟수(3번)를 깎으면 안 된다.
    """
    import asyncio

    from aist.config import Config
    from aist.orchestrator import Orchestrator
    from aist.persona import Persona

    cfg = Config()
    cfg.memory.path = str(tmp_path / "m")
    o = Orchestrator(cfg, Persona())
    o.memory.start_session()
    c = _controller()
    c.connected = lambda: True
    n = asyncio.run(o._refresh_web_ui(c, why="방송 시작 전"))
    assert n == 1 and c._client.pressed
    assert o._web_refreshes == 0
    assert not [e for e in o.memory._cur["events"] if e["kind"] == "web_ui_refresh"]
    # 사고 때는 예전처럼 센다
    asyncio.run(o._refresh_web_ui(c))
    assert o._web_refreshes == 1
    assert [e for e in o.memory._cur["events"] if e["kind"] == "web_ui_refresh"]


def test_코어_창에_찍힌_localhost_주소도_같은_코어로_본다():
    """코어는 'Uvicorn running on http://localhost:12393' 을 찍고, 운영자는
    그걸 OBS 에 그대로 넣는다. 우리 기본 주소는 127.0.0.1:12393 이라 글자
    비교로는 한 번도 안 맞아 새로고침이 영영 안 됐다."""
    from aist.obs_control import same_core_address as same
    assert same("http://localhost:12393/", "127.0.0.1:12393")
    assert same("http://127.0.0.1:12393", "localhost:12393")
    assert same("http://192.168.0.5:12393/", "127.0.0.1:12393")   # 다른 PC 의 OBS
    assert not same("http://localhost:9999/", "127.0.0.1:12393")
    assert not same("https://alerts.example.com/w/abc", "127.0.0.1:12393")
    assert not same("", "127.0.0.1:12393")


def test_localhost_로_넣은_브라우저_소스도_새로고침한다():
    c = _controller()
    c._client.get_input_settings = lambda name: c._client._R(
        input_settings={"url": {"웹UI": "http://localhost:12393/",
                                "알림창": "https://alerts.example.com/w/abc"}[name]})
    assert c.refresh_browser_sources("127.0.0.1:12393") == 1
    assert c._client.pressed == [("웹UI", "refreshnocache")]
