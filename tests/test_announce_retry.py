"""공지가 한 번 실패하면 그대로 끝나던 것.

공지는 방송당 한두 번뿐인데, 그 한 번이 네트워크 순단으로 실패하면
시청자는 방송이 켜진 걸 모른다 — 기획안 2-2② 의 기본 동선이 통째로 빠진다.
그런데 디스코드도 네이버도 네트워크 오류에 재시도가 없었다.

무턱대고 재시도하면 안 된다. 4xx(채널 ID 오타, 죽은 토큰)는 다시 보내도
똑같이 실패하고, 카페는 계정 리스크가 있다(기획안 5-2 "빈도 낮게").
"""

import pytest

from aist.announce.retry import (DEFAULT_ATTEMPTS, post_with_retry,
                                 should_retry_status)


# --------------------------- 어떤 실패를 다시 해볼까 ------------------------
@pytest.mark.parametrize("status", [429, 500, 502, 503, 504, None])
def test_transient_failures_are_retried(status):
    assert should_retry_status(status) is True


@pytest.mark.parametrize("status", [400, 401, 403, 404, 405, 413])
def test_permanent_failures_are_not_retried(status):
    """설정·권한 문제는 다시 보내도 똑같이 실패한다."""
    assert should_retry_status(status) is False


# --------------------------- 재시도 흐름 -----------------------------------
def _runner(results):
    it = iter(results)
    calls = {"n": 0}

    def send():
        calls["n"] += 1
        try:
            return next(it)
        except StopIteration:
            return (False, 503, "bad")

    return send, calls


def test_first_try_success_does_not_sleep():
    send, calls = _runner([(True, 200, "")])
    slept = []
    assert post_with_retry(send, what="t", sleep=slept.append) is True
    assert calls["n"] == 1 and slept == []


def test_network_error_then_success():
    send, calls = _runner([(False, None, "연결 끊김"), (True, 200, "")])
    slept = []
    assert post_with_retry(send, what="t", sleep=slept.append) is True
    assert calls["n"] == 2 and len(slept) == 1


def test_gives_up_after_attempts():
    send, calls = _runner([(False, 503, "bad")] * 5)
    slept = []
    assert post_with_retry(send, what="t", sleep=slept.append) is False
    assert calls["n"] == DEFAULT_ATTEMPTS


def test_permanent_error_stops_immediately():
    send, calls = _runner([(False, 401, "unauthorized")] * 5)
    slept = []
    assert post_with_retry(send, what="t", sleep=slept.append) is False
    assert calls["n"] == 1, "설정 문제인데 반복 시도했다"
    assert slept == []


def test_rate_limit_is_retried():
    send, calls = _runner([(False, 429, "rate limited"), (True, 200, "")])
    assert post_with_retry(send, what="t", sleep=lambda s: None) is True
    assert calls["n"] == 2


def test_backoff_grows():
    send, _ = _runner([(False, 503, "bad")] * 5)
    slept = []
    post_with_retry(send, what="t", attempts=4, backoff_sec=1.0, sleep=slept.append)
    assert slept == [1.0, 2.0, 3.0], slept


def test_failure_says_viewers_did_not_get_it(caplog):
    send, _ = _runner([(False, 503, "bad")] * 5)
    post_with_retry(send, what="디스코드 공지", sleep=lambda s: None)
    assert any("공지가 안 나갔습니다" in r.getMessage() for r in caplog.records)


# --------------------------- 디스코드 실제 경로 -----------------------------
def test_discord_retries_on_server_error(monkeypatch):
    from aist.announce.discord_bot import DiscordAnnouncer
    from aist.config import DiscordAnnounce

    calls = {"n": 0}

    class Resp:
        def __init__(self, code):
            self.status_code = code
            self.text = "err"

    def fake_post(*a, **k):
        calls["n"] += 1
        return Resp(200 if calls["n"] >= 2 else 503)

    import requests
    monkeypatch.setattr(requests, "post", fake_post)
    monkeypatch.setattr("time.sleep", lambda s: None)
    ann = DiscordAnnouncer(DiscordAnnounce(channel_id=1), "token")
    assert ann._post_sync({"content": "x"}) is True
    assert calls["n"] == 2


def test_discord_does_not_retry_on_bad_channel(monkeypatch):
    from aist.announce.discord_bot import DiscordAnnouncer
    from aist.config import DiscordAnnounce

    calls = {"n": 0}

    class Resp:
        status_code = 404
        text = "Unknown Channel"

    def fake_post(*a, **k):
        calls["n"] += 1
        return Resp()

    import requests
    monkeypatch.setattr(requests, "post", fake_post)
    monkeypatch.setattr("time.sleep", lambda s: None)
    ann = DiscordAnnouncer(DiscordAnnounce(channel_id=999), "token")
    assert ann._post_sync({"content": "x"}) is False
    assert calls["n"] == 1, "채널이 없는데 반복 시도했다"
