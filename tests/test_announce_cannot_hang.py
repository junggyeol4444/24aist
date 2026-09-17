"""공지 하나가 방송을 붙잡지 못하게.

시작 공지는 방송이 켜지기 전에 돈다. 네이버 카페 셀레늄 경로는 브라우저를
띄우는데, 페이지가 안 열리면 driver.get() 은 기본적으로 영원히 기다린다.
거기서 멎으면 방송이 아예 안 켜지고, 무인 운영에서는 아무도 모른 채
밤이 지나간다.
"""

import asyncio
import logging

from aist.config import Config
from aist.orchestrator import Orchestrator, _ANNOUNCE_TIMEOUT_SEC
from aist.persona import Persona


class _Hang:
    name = "멎는공지"

    async def post(self, text, *, title=""):
        await asyncio.sleep(9999)

    async def close(self):
        return None


class _Ok:
    name = "정상공지"

    def __init__(self):
        self.posted = []

    async def post(self, text, *, title=""):
        self.posted.append(text)
        return True

    async def close(self):
        return None


def _orch(tmp_path):
    cfg = Config()
    cfg.memory.path = str(tmp_path / "mem")
    cfg.announce.on_start = True
    return Orchestrator(cfg, Persona())


def test_멎는_공지는_상한에서_끊고_방송은_계속된다(tmp_path, caplog, monkeypatch):
    o = _orch(tmp_path)
    hang, ok = _Hang(), _Ok()
    monkeypatch.setattr(o, "_announcers", lambda: [hang, ok])
    monkeypatch.setattr("aist.orchestrator._ANNOUNCE_TIMEOUT_SEC", 0.2)
    monkeypatch.setattr("aist.orchestrator.should_post", lambda now, cfg: True)
    monkeypatch.setattr("aist.orchestrator.compose",
                        lambda *a, **k: "오늘 방송 켰어요")

    from datetime import datetime, timezone
    with caplog.at_level(logging.ERROR):
        asyncio.run(o._announce("start", datetime.now(timezone.utc)))

    assert any("안 끝나" in r.getMessage() for r in caplog.records)
    # 멎은 공지 하나 때문에 뒤의 공지가 통째로 빠지면 안 된다
    assert ok.posted == ["오늘 방송 켰어요"]


def test_상한은_재시도까지_감안한_값이다():
    # 3회 재시도 + 셀레늄 브라우저 기동을 감안. 너무 짧으면 정상 공지를 끊는다.
    assert _ANNOUNCE_TIMEOUT_SEC >= 60


# --------- 본문을 못 넣었는데 등록을 누르면 빈 글이 카페에 올라간다 ---------
def _fake_selenium(monkeypatch, body_found: bool, clicks: list):
    """selenium 을 통째로 흉내낸다 — 진짜 브라우저 없이 그 경로를 돌린다."""
    import sys
    import types

    class _El:
        def __init__(self, kind):
            self.kind = kind

        def send_keys(self, *a):
            pass

        def click(self):
            clicks.append(self.kind)

    class _Wait:
        def __init__(self, driver, t):
            pass

        def until(self, cond):
            return cond(None)

    class _Driver:
        def __init__(self, options=None):
            self.switch_to = types.SimpleNamespace(
                frame=lambda f: None, default_content=lambda: None)

        def set_page_load_timeout(self, t):
            pass

        def set_script_timeout(self, t):
            pass

        def get(self, url):
            pass

        def add_cookie(self, c):
            pass

        def find_elements(self, by, sel):
            return [_El("body")] if body_found else []

        def quit(self):
            pass

    sel = types.ModuleType("selenium")
    sel.webdriver = types.ModuleType("selenium.webdriver")
    sel.webdriver.Chrome = _Driver
    chrome_opts = types.ModuleType("selenium.webdriver.chrome.options")
    chrome_opts.Options = lambda: types.SimpleNamespace(add_argument=lambda *a: None)
    common_by = types.ModuleType("selenium.webdriver.common.by")
    common_by.By = types.SimpleNamespace(CSS_SELECTOR="css", XPATH="xpath",
                                         TAG_NAME="tag")
    ui = types.ModuleType("selenium.webdriver.support.ui")
    ui.WebDriverWait = _Wait
    ec = types.ModuleType("selenium.webdriver.support.expected_conditions")
    ec.presence_of_element_located = lambda loc: (lambda d: _El("제목"))
    ec.element_to_be_clickable = lambda loc: (lambda d: _El("등록"))
    ec.url_changes = lambda url: (lambda d: True)

    chrome = types.ModuleType("selenium.webdriver.chrome")
    chrome.options = chrome_opts
    common = types.ModuleType("selenium.webdriver.common")
    common.by = common_by
    support = types.ModuleType("selenium.webdriver.support")
    support.ui = ui
    support.expected_conditions = ec
    sel.webdriver.chrome = chrome
    sel.webdriver.common = common
    sel.webdriver.support = support

    for name, mod in [("selenium", sel),
                      ("selenium.webdriver", sel.webdriver),
                      ("selenium.webdriver.chrome", chrome),
                      ("selenium.webdriver.chrome.options", chrome_opts),
                      ("selenium.webdriver.common", common),
                      ("selenium.webdriver.common.by", common_by),
                      ("selenium.webdriver.support", support),
                      ("selenium.webdriver.support.ui", ui),
                      ("selenium.webdriver.support.expected_conditions", ec)]:
        monkeypatch.setitem(sys.modules, name, mod)


def _cafe():
    from aist.announce.naver_cafe import NaverCafeAnnouncer
    from aist.config import NaverCafeAnnounce, Secrets
    cfg = NaverCafeAnnounce(enabled=True, cafe_id="123", menu_id="4")
    sec = Secrets()
    sec.naver_nid_aut, sec.naver_nid_ses = "aut", "ses"
    return NaverCafeAnnouncer(cfg, sec)


def test_본문을_못_넣으면_등록을_안_누른다(monkeypatch, caplog):
    clicks = []
    _fake_selenium(monkeypatch, body_found=False, clicks=clicks)
    with caplog.at_level(logging.ERROR):
        ok = _cafe()._selenium_post("방송 시작", "오늘 방송 켰어요")
    assert ok is False, "빈 글을 올려놓고 성공이라고 했다"
    assert "등록" not in clicks, "본문 없이 등록을 눌렀다"
    assert any("본문 입력 영역을 못 찾" in r.getMessage() for r in caplog.records)


def test_본문이_들어가면_등록을_누른다(monkeypatch):
    clicks = []
    _fake_selenium(monkeypatch, body_found=True, clicks=clicks)
    assert _cafe()._selenium_post("방송 시작", "오늘 방송 켰어요") is True
    assert "등록" in clicks
