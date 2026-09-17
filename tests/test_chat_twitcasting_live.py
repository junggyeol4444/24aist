"""트위캐스팅 채팅 리더를 진짜 HTTP 로 돌려본다.

이 플랫폼은 폴링이라 "연결 끊김" 이 없다. 대신 방송이 한 번 끝났다가
다시 켜지면 movie 가 바뀌는데, 예전 movie 만 계속 찔러보면 채팅이 조용히
멈춘다 — 프로그램은 멀쩡히 도는 것처럼 보인다.
"""

import asyncio
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

pytest.importorskip("requests")

import aist.chat.twitcasting as tc  # noqa: E402
from aist.chat.twitcasting import TwitcastingChat  # noqa: E402


class _Api:
    """current_live 와 comments 를 흉내. 도중에 방송이 바뀐다."""

    def __init__(self):
        self.movie = "movie1"
        self.comments = {
            "movie1": [{"id": "c1", "message": "지난 댓글",
                        "from_user": {"name": "옛날사람"}}],
            "movie2": [{"id": "c9", "message": "새 방송 안녕",
                        "from_user": {"name": "새시청자"}}],
        }
        self.ended = set()
        self.paths = []
        rec = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                rec.paths.append(self.path.split("?")[0])
                if self.path.endswith("/current_live"):
                    body = {"movie": {"id": rec.movie}}
                    return self._json(200, body)
                mid = self.path.split("/movies/")[1].split("/")[0]
                if mid in rec.ended:
                    return self._json(404, {"error": "gone"})
                return self._json(200, {"comments": rec.comments.get(mid, [])})

            def _json(self, code, obj):
                raw = json.dumps(obj, ensure_ascii=False).encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

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


def test_new_comments_flow_and_old_ones_are_skipped(monkeypatch):
    with _Api() as api:
        monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
        monkeypatch.setenv("no_proxy", "127.0.0.1,localhost")
        monkeypatch.setattr(tc, "_API", api.base)
        chat = TwitcastingChat("bj", "abcdef123456", poll_interval=0.1)

        async def main():
            msgs = []

            async def read():
                async for m in chat.messages():
                    msgs.append(m)
                    if len(msgs) >= 1:
                        return

            # 첫 폴링분(과거 댓글)은 흘리지 않는다 → 새 댓글을 하나 넣는다
            async def add_later():
                await asyncio.sleep(0.4)
                api.comments["movie1"].append(
                    {"id": "c2", "message": "지금 왔어요",
                     "from_user": {"name": "현재시청자"}})

            asyncio.create_task(add_later())
            try:
                await asyncio.wait_for(read(), timeout=15)
            finally:
                await chat.close()
            return msgs

        msgs = asyncio.run(main())
    assert [(m.author, m.text) for m in msgs] == [("현재시청자", "지금 왔어요")]


def test_finds_the_new_broadcast_after_restart(monkeypatch):
    """방송이 끝났다 다시 켜지면 movie 가 바뀐다 — 예전 것만 찔러보면 안 된다."""
    with _Api() as api:
        monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
        monkeypatch.setenv("no_proxy", "127.0.0.1,localhost")
        monkeypatch.setattr(tc, "_API", api.base)
        chat = TwitcastingChat("bj", "abcdef123456", poll_interval=0.1)

        async def main():
            msgs = []

            async def read():
                async for m in chat.messages():
                    msgs.append(m)
                    if len(msgs) >= 1:
                        return

            async def restart():
                await asyncio.sleep(0.5)
                api.ended.add("movie1")       # 방송 종료
                api.movie = "movie2"          # 새 방송
                await asyncio.sleep(0.5)
                api.comments["movie2"].append(
                    {"id": "c10", "message": "새 방송 채팅",
                     "from_user": {"name": "새사람"}})

            asyncio.create_task(restart())
            try:
                await asyncio.wait_for(read(), timeout=20)
            finally:
                await chat.close()
            return msgs

        msgs = asyncio.run(main())
    assert msgs and msgs[0].text == "새 방송 채팅", "새 방송을 못 찾았습니다"


def test_seen_ids_do_not_grow_without_limit():
    """몇 시간 돌면 id 가 수천 개 쌓인다 — 상한이 있어야 한다."""
    chat = TwitcastingChat("bj", "abcdef123456")
    assert tc._SEEN_MAX < 100000 and tc._SEEN_KEEP < tc._SEEN_MAX
