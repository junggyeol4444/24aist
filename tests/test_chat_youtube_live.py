"""유튜브 라이브 자동발견을 실제 HTTP 로 확인한다.

video_id 는 방송마다 바뀐다. 사람 손 없이 돌려면 채널 페이지에서 지금
라이브의 videoId 를 찾아내야 하는데, 이건 비공식 방법이라 페이지가 바뀌면
조용히 실패한다. 최소한 "라이브일 때 찾고, 아닐 때는 None" 은 지켜야 한다.
"""

import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

pytest.importorskip("requests")

import aist.chat.youtube as yt  # noqa: E402


class _Site:
    def __init__(self, live: bool = True, status: int = 200):
        self.live = live
        self.status = status
        self.paths = []
        rec = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                rec.paths.append(self.path)
                body = b"<html>not live</html>"
                if rec.live:
                    body = ('<html>{"isLiveNow":true,'
                            '"videoId":"abcdefghijk"}</html>').encode("utf-8")
                self.send_response(rec.status)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *a):
                pass

        self.httpd = HTTPServer(("127.0.0.1", 0), Handler)

    def __enter__(self):
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        return self

    def __exit__(self, *exc):
        self.httpd.shutdown()
        return False

    @property
    def base(self):
        return "http://%s:%s" % self.httpd.server_address


def _resolve(site, channel, monkeypatch):
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    monkeypatch.setenv("no_proxy", "127.0.0.1,localhost")
    monkeypatch.setattr(yt, "_BASE", site.base)
    return yt.resolve_live_video_id(channel)


def test_finds_video_id_for_handle(monkeypatch):
    with _Site(live=True) as site:
        assert _resolve(site, "별이채널", monkeypatch) == "abcdefghijk"
        # 한글 핸들은 퍼센트 인코딩돼 나간다(정상)
        from urllib.parse import unquote
        assert unquote(site.paths[0]) == "/@별이채널/live"


def test_finds_video_id_for_channel_id(monkeypatch):
    with _Site(live=True) as site:
        assert _resolve(site, "UC1234567890abcdefghij", monkeypatch) == "abcdefghijk"
        assert site.paths == ["/channel/UC1234567890abcdefghij/live"]


def test_not_live_returns_none(monkeypatch):
    """방송 전이면 None 이어야 한다 — 엉뚱한 영상에 붙으면 안 된다."""
    with _Site(live=False) as site:
        assert _resolve(site, "@별이채널", monkeypatch) is None


def test_error_page_returns_none(monkeypatch):
    with _Site(live=True, status=404) as site:
        assert _resolve(site, "@별이채널", monkeypatch) is None
