"""네이버 카페 공지 — EUC-KR 인코딩.

카페 글쓰기 API 는 EUC-KR 을 요구하는데 공지 문구에는 기본으로 이모지가
섞인다. 이모지 하나에 공지 전체가 안 올라가면 안 된다.
"""

from urllib.parse import quote

from aist.announce.naver_cafe import NaverCafeAnnouncer, _euckr_safe
from aist.config import NaverCafeAnnounce, Secrets


def test_emoji_is_dropped_not_fatal():
    out = _euckr_safe("오늘도 달려봅시다 ✨🔥")
    assert "달려봅시다" in out
    quote(out, encoding="euc-kr")          # 여기서 터지면 공지가 안 나간다


def test_plain_korean_is_untouched():
    s = "오늘 19시에 방송 시작합니다.\n놀러오세요!"
    assert _euckr_safe(s) == s


def test_official_post_sends_body_with_emoji(monkeypatch):
    """이모지가 든 공지도 실제로 전송까지 간다."""
    sent = {}

    class _Resp:
        status_code = 200
        text = "ok"

    class _Requests:
        @staticmethod
        def post(url, headers=None, data=None, timeout=None):
            sent["data"] = data
            return _Resp()

    import sys
    monkeypatch.setitem(sys.modules, "requests", _Requests)
    a = NaverCafeAnnouncer(
        NaverCafeAnnounce(enabled=True, cafe_id="1", menu_id="2"),
        Secrets(naver_access_token="tok"),
    )
    assert a._official_post("방송 공지 ✨", "지금 시작합니다 🔥") is True
    assert b"subject=" in sent["data"]
    sent["data"].decode("ascii")           # ascii 여야 전송 가능
