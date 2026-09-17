"""디스코드 공지를 진짜 HTTP 로 주고받아 본다.

공지는 방송당 한두 번뿐이라, 실패하면 시청자는 방송이 켜진 걸 모른다.
그런데 지금까지는 requests.post 를 가짜로 바꿔치기해서만 확인했다 —
"우리가 보내는 요청이 디스코드가 받는 모양인지" 는 검증되지 않았다.
작은 HTTP 서버를 띄워 실제로 보내본다.
"""

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

pytest.importorskip("requests")

import aist.announce.discord_bot as db  # noqa: E402
from aist.announce.discord_bot import DiscordAnnouncer  # noqa: E402
from aist.config import DiscordAnnounce  # noqa: E402


class _Recorder:
    def __init__(self, statuses):
        self.statuses = list(statuses)
        self.requests = []


def _server(rec: _Recorder):
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            rec.requests.append({
                "path": self.path,
                "auth": self.headers.get("Authorization"),
                "content_type": self.headers.get("Content-Type", ""),
                "body": body,
            })
            status = rec.statuses.pop(0) if rec.statuses else 200
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"id":"1"}')

        def log_message(self, *a):
            pass

    httpd = HTTPServer(("127.0.0.1", 0), Handler)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    return httpd


def _announce(rec, monkeypatch, **cfg_kw):
    httpd = _server(rec)
    host, port = httpd.server_address
    # 이 환경은 HTTP 프록시를 환경변수로 쓴다 — 로컬 테스트 서버로 가는
    # 요청이 프록시로 새지 않게 막는다(제품 동작과는 무관).
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    monkeypatch.setenv("no_proxy", "127.0.0.1,localhost")
    monkeypatch.setattr(db, "_API", f"http://{host}:{port}")
    monkeypatch.setattr("time.sleep", lambda s: None)      # 재시도 대기 건너뛰기
    cfg = DiscordAnnounce(enabled=True, channel_id=123456, **cfg_kw)
    return DiscordAnnouncer(cfg, "MTIzNDU2.Bot.Token"), httpd


def test_posts_to_the_right_place_with_the_right_body(monkeypatch):
    rec = _Recorder([200])
    ann, httpd = _announce(rec, monkeypatch)
    try:
        assert ann._post_sync(ann.build_payload("오늘 방송 시작했어요!")) is True
    finally:
        httpd.shutdown()
    req = rec.requests[0]
    assert req["path"] == "/channels/123456/messages"
    assert req["auth"] == "Bot MTIzNDU2.Bot.Token"
    assert "application/json" in req["content_type"]
    body = json.loads(req["body"].decode("utf-8"))
    assert body["content"] == "오늘 방송 시작했어요!"
    assert body["allowed_mentions"] == {"parse": []}      # 기본은 멘션 안 함


def test_role_mention_is_allowed_only_for_that_role(monkeypatch):
    rec = _Recorder([200])
    ann, httpd = _announce(rec, monkeypatch, mention_role_id=777)
    try:
        ann._post_sync(ann.build_payload("시작합니다"))
    finally:
        httpd.shutdown()
    body = json.loads(rec.requests[0]["body"].decode("utf-8"))
    assert body["content"].startswith("<@&777>")
    assert body["allowed_mentions"] == {"roles": ["777"]}


def test_retries_on_server_error_then_succeeds(monkeypatch):
    rec = _Recorder([503, 200])
    ann, httpd = _announce(rec, monkeypatch)
    try:
        assert ann._post_sync(ann.build_payload("시작")) is True
    finally:
        httpd.shutdown()
    assert len(rec.requests) == 2, "5xx 인데 다시 시도하지 않았습니다"


def test_retries_on_rate_limit(monkeypatch):
    rec = _Recorder([429, 200])
    ann, httpd = _announce(rec, monkeypatch)
    try:
        assert ann._post_sync(ann.build_payload("시작")) is True
    finally:
        httpd.shutdown()
    assert len(rec.requests) == 2


def test_does_not_retry_on_unknown_channel(monkeypatch):
    """채널 ID 가 틀리면 몇 번을 보내도 똑같이 실패한다 — 계정 리스크만 는다."""
    rec = _Recorder([404, 404, 404])
    ann, httpd = _announce(rec, monkeypatch)
    try:
        assert ann._post_sync(ann.build_payload("시작")) is False
    finally:
        httpd.shutdown()
    assert len(rec.requests) == 1


def test_embed_with_local_image_is_sent_as_multipart(tmp_path, monkeypatch):
    img = tmp_path / "thumb.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 32)
    rec = _Recorder([200])
    ann, httpd = _announce(rec, monkeypatch, use_embed=True, image_path=str(img))
    try:
        assert ann._post_sync(ann.build_payload("오늘 방송", "방송 시작")) is True
    finally:
        httpd.shutdown()
    req = rec.requests[0]
    assert "multipart/form-data" in req["content_type"]
    assert b"payload_json" in req["body"] and b"thumb.png" in req["body"]
