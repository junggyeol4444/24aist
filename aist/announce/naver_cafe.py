"""네이버 카페 공지 (5-2).

경로 A: 공식 오픈 API (권장/1순위)
  - 글쓰기: POST https://openapi.naver.com/v1/cafe/{cafe_id}/menu/{menu_id}/articles
  - 헤더: Authorization: Bearer {access_token}
  - subject/content 는 EUC-KR 로 URL 인코딩해 폼으로 전송(네이버 규격)
  - access token 만료 시 refresh_token 으로 갱신
경로 B: 셀레늄 (보조) — 공식 API 로 안 되는 부분만. 본인 카페 + 저빈도
  + 자연스러운 패턴. 기본 비활성. 필요 시 _selenium_post 채워서 사용.

주의: 자동 게시 빈도를 낮게(방송당 1회 정도) 유지해 계정 리스크 최소화.
requests 지연 import, 호출은 asyncio.to_thread.
"""

import asyncio
import logging
from typing import Optional
from urllib.parse import quote

from ..config import NaverCafeAnnounce
from ..config import Secrets
from .base import Announcer

log = logging.getLogger("aist.announce.naver")

_ARTICLE_API = "https://openapi.naver.com/v1/cafe/{cafe_id}/menu/{menu_id}/articles"
_TOKEN_API = "https://nid.naver.com/oauth2.0/token"


class NaverCafeAnnouncer(Announcer):
    name = "naver_cafe"

    def __init__(self, cfg: NaverCafeAnnounce, secrets: Secrets):
        self.cfg = cfg
        self.secrets = secrets
        self._access_token = secrets.naver_access_token

    async def post(self, text: str, *, title: str = "") -> bool:
        if not self.cfg.enabled:
            return False
        if self.cfg.use_official_api:
            ok = await asyncio.to_thread(self._official_post, title or "방송 공지", text)
            if ok:
                return True
            if self.cfg.use_selenium_fallback:
                log.info("공식 API 실패 → 셀레늄 보조 시도")
                return await asyncio.to_thread(self._selenium_post, title or "방송 공지", text)
            return False
        if self.cfg.use_selenium_fallback:
            return await asyncio.to_thread(self._selenium_post, title or "방송 공지", text)
        log.warning("네이버 카페: 사용할 게시 경로가 없음(공식/셀레늄 둘 다 off)")
        return False

    # --- 경로 A: 공식 API --------------------------------------------------
    def _official_post(self, subject: str, content: str, _retry: bool = True) -> bool:
        try:
            import requests  # 지연 import
        except ImportError:
            log.error("requests 미설치: `pip install requests`")
            return False
        if not (self.cfg.cafe_id and self.cfg.menu_id and self._access_token):
            log.warning("네이버 카페 cafe_id/menu_id/access_token 미설정 → 생략")
            return False
        url = _ARTICLE_API.format(cafe_id=self.cfg.cafe_id, menu_id=self.cfg.menu_id)
        # 네이버 카페 글쓰기 API 는 subject/content 를 EUC-KR 로 인코딩해야 함
        body = (
            "subject=" + quote(subject, encoding="euc-kr")
            + "&content=" + quote(content, encoding="euc-kr")
        )
        try:
            r = requests.post(
                url,
                headers={
                    "Authorization": f"Bearer {self._access_token}",
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                data=body.encode("ascii"),
                timeout=15,
            )
            if r.status_code == 200:
                log.info("네이버 카페 공지 게시 완료(공식 API)")
                return True
            if r.status_code == 401 and _retry and self._refresh_token():
                return self._official_post(subject, content, _retry=False)
            log.error("네이버 카페 공지 실패 (%s): %s", r.status_code, r.text[:300])
            return False
        except Exception as e:  # noqa: BLE001
            log.error("네이버 카페 공지 예외: %s", e)
            return False

    def _refresh_token(self) -> bool:
        try:
            import requests
        except ImportError:
            return False
        s = self.secrets
        if not (s.naver_client_id and s.naver_client_secret and s.naver_refresh_token):
            return False
        try:
            r = requests.get(
                _TOKEN_API,
                params={
                    "grant_type": "refresh_token",
                    "client_id": s.naver_client_id,
                    "client_secret": s.naver_client_secret,
                    "refresh_token": s.naver_refresh_token,
                },
                timeout=15,
            )
            data = r.json()
            tok = data.get("access_token")
            if tok:
                self._access_token = tok
                log.info("네이버 access token 갱신됨")
                return True
            log.error("네이버 토큰 갱신 실패: %s", data)
            return False
        except Exception as e:  # noqa: BLE001
            log.error("네이버 토큰 갱신 예외: %s", e)
            return False

    # --- 경로 B: 셀레늄 (보조, 기본 미구현) --------------------------------
    def _selenium_post(self, subject: str, content: str) -> bool:
        raise NotImplementedError(
            "셀레늄 보조 게시는 기본 미구현입니다. 공식 API 로 안 되는 부분이 "
            "생기면, 본인 카페 + 낮은 빈도 + 자연스러운 패턴 조건에서만 "
            "aist/announce/naver_cafe.py 의 _selenium_post 를 채워 쓰세요."
        )
