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
