"""네이버 카페 공지를 진짜 HTTP 로 보내본다(로컬 서버 상대).

카페 API 는 EUC-KR 을 요구한다. "코드가 돈다" 로는 확인이 안 되고,
실제로 보낸 바이트가 EUC-KR 한글인지, 토큰이 만료됐을 때 갱신하고 다시
보내는지를 봐야 한다.
"""

import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

pytest.importorskip("requests")

import aist.announce.naver_cafe as nc  # noqa: E402
from aist.announce.naver_cafe import NaverCafeAnnouncer  # noqa: E402
from aist.config import NaverCafeAnnounce, Secrets  # noqa: E402


class _Server:
    def __init__(self, post_statuses=(200,)):
        self.statuses = list(post_statuses)
        self.posts = []
        self.token_refreshes = 0
        rec = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                n = int(self.headers.get("Content-Length", 0))
                rec.posts.append({"path": self.path,
                                  "auth": self.headers.get("Authorization"),
                                  "body": self.rfile.read(n)})
                code = rec.statuses.pop(0) if rec.statuses else 200
                self.send_response(code)
                self.end_headers()
                self.wfile.write(b"{}")

            def do_GET(self):
                rec.token_refreshes += 1
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"access_token":"new-token"}')

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


def _announcer(server, monkeypatch, **secret_kw):
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    monkeypatch.setenv("no_proxy", "127.0.0.1,localhost")
    monkeypatch.setattr(nc, "_ARTICLE_API",
                        server.base + "/cafe/{cafe_id}/menu/{menu_id}/articles")
    monkeypatch.setattr(nc, "_TOKEN_API", server.base + "/oauth2.0/token")
    monkeypatch.setattr("time.sleep", lambda s: None)
    return NaverCafeAnnouncer(
        NaverCafeAnnounce(enabled=True, cafe_id="12345", menu_id="7"),
        Secrets(naver_access_token="old-token", **secret_kw))


def _fields(body: bytes) -> dict:
    """보낸 폼 본문 → {필드: 원래 문자열}. 네이버가 읽는 방식대로 EUC-KR 로."""
    out = {}
    for field in body.decode("ascii").split("&"):
        k, _, v = field.partition("=")
        out[k] = urllib.parse.unquote_to_bytes(v).decode("euc-kr")
    return out


def test_body_is_real_euckr_korean(monkeypatch):
    with _Server() as s:
        ann = _announcer(s, monkeypatch)
        assert ann._official_post("방송 시작 ✨", "오늘도 시작합니다! 🔥\n놀러오세요~") is True
    f = _fields(s.posts[0]["body"])
    assert f["subject"] == "방송 시작 "          # 이모지는 EUC-KR 에 없어서 빠진다
    assert f["content"].startswith("오늘도 시작합니다!")
    assert "놀러오세요~" in f["content"]
    assert s.posts[0]["path"] == "/cafe/12345/menu/7/articles"
    assert s.posts[0]["auth"] == "Bearer old-token"


def test_expired_token_is_refreshed_and_retried(monkeypatch):
    """토큰은 만료된다. 그때 한 번은 갱신해서 다시 보내야 공지가 나간다."""
    with _Server(post_statuses=(401, 200)) as s:
        ann = _announcer(s, monkeypatch, naver_client_id="id",
                         naver_client_secret="secret", naver_refresh_token="refresh")
        assert ann._official_post("방송 시작", "본문") is True
    assert s.token_refreshes == 1
    assert len(s.posts) == 2
    assert s.posts[1]["auth"] == "Bearer new-token"


def test_gives_up_without_refresh_credentials(monkeypatch):
    """갱신에 필요한 값이 없으면 헛되이 반복하지 않는다(계정 리스크)."""
    with _Server(post_statuses=(401, 401, 401)) as s:
        ann = _announcer(s, monkeypatch)          # refresh_token 없음
        assert ann._official_post("방송 시작", "본문") is False
    assert s.token_refreshes == 0
    assert len(s.posts) == 1
