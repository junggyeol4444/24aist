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

    # --- 경로 B: 셀레늄 (보조) ---------------------------------------------
    def _selenium_post(self, subject: str, content: str) -> bool:
        """브라우저 자동화로 카페 글 작성(공식 API 로 안 되는 부분 보조).

        로그인은 캡차를 피하려고 자동 로그인 대신 **쿠키(NID_AUT/NID_SES)**로
        붙는다(.env). 본인 카페 + 낮은 빈도(방송당 1회)로만 쓸 것.

        [주의] 네이버 카페 글쓰기 화면은 SPA + 에디터 iframe 이라 DOM 이 자주
        바뀐다. 아래 셀렉터는 표준 구조 기준이며, 실제로 한 번 돌려보고
        (STEP 로그를 보며) 셀렉터를 조정해야 할 수 있다. 실패해도 예외 대신
        False 를 돌려 방송은 계속되게 한다.
        """
        aut = self.secrets.naver_nid_aut
        ses = self.secrets.naver_nid_ses
        if not (self.cfg.cafe_id and self.cfg.menu_id):
            log.warning("셀레늄: cafe_id/menu_id 미설정 → 생략")
            return False
        if not (aut and ses):
            log.warning("셀레늄: NID_AUT/NID_SES 쿠키 미설정(.env) → 생략")
            return False
        try:
            from selenium import webdriver
            from selenium.webdriver.chrome.options import Options
            from selenium.webdriver.common.by import By
            from selenium.webdriver.support.ui import WebDriverWait
            from selenium.webdriver.support import expected_conditions as EC
        except ImportError:
            log.error("selenium 미설치: `pip install selenium`")
            return False

        opts = Options()
        opts.add_argument("--headless=new")
        opts.add_argument("--no-sandbox")
        opts.add_argument("--disable-dev-shm-usage")
        opts.add_argument("--window-size=1280,1000")
        driver = None
        try:
            driver = webdriver.Chrome(options=opts)
            wait = WebDriverWait(driver, 15)

            log.info("셀레늄 STEP1: 쿠키 로그인")
            driver.get("https://www.naver.com")
            for name, val in (("NID_AUT", aut), ("NID_SES", ses)):
                driver.add_cookie({"name": name, "value": val, "domain": ".naver.com"})

            log.info("셀레늄 STEP2: 글쓰기 페이지 열기")
            write_url = (
                f"https://cafe.naver.com/ca-fe/cafes/{self.cfg.cafe_id}"
                f"/menus/{self.cfg.menu_id}/articles/write"
            )
            driver.get(write_url)

            log.info("셀레늄 STEP3: 제목 입력")
            subj = wait.until(EC.presence_of_element_located(
                (By.CSS_SELECTOR, "textarea.textarea_input, input.textarea_input, "
                                  "textarea[placeholder*='제목'], input[placeholder*='제목']")))
            subj.send_keys(subject)

            log.info("셀레늄 STEP4: 본문 입력(에디터)")
            # SmartEditor 본문은 보통 contenteditable 영역 or iframe.
            body_written = self._selenium_type_body(driver, By, content)
            if not body_written:
                log.warning("셀레늄: 본문 입력 영역을 못 찾음(셀렉터 조정 필요)")

            log.info("셀레늄 STEP5: 등록 버튼 클릭")
            btn = wait.until(EC.element_to_be_clickable(
                (By.XPATH, "//*[self::button or self::a]"
                           "[contains(text(),'등록') or contains(text(),'확인')]")))
            btn.click()
            WebDriverWait(driver, 10).until(EC.url_changes(write_url))
            log.info("네이버 카페 공지 게시 완료(셀레늄)")
            return True
        except Exception as e:  # noqa: BLE001
            log.error("셀레늄 게시 실패(셀렉터/로그인 확인 필요): %s", e)
            return False
        finally:
            if driver is not None:
                try:
                    driver.quit()
                except Exception:
                    pass

    @staticmethod
    def _selenium_type_body(driver, By, content: str) -> bool:
        """본문 입력을 여러 방식으로 시도(에디터 구조가 다양)."""
        # 1) 일반 contenteditable
        for sel in ("div.se-content [contenteditable='true']",
                    "div[contenteditable='true']", ".ProseMirror"):
            els = driver.find_elements(By.CSS_SELECTOR, sel)
            if els:
                els[0].click()
                els[0].send_keys(content)
                return True
        # 2) 에디터 iframe 안쪽
        for frame in driver.find_elements(By.TAG_NAME, "iframe"):
            try:
                driver.switch_to.frame(frame)
                els = driver.find_elements(By.CSS_SELECTOR, "body[contenteditable='true'], .ProseMirror")
                if els:
                    els[0].send_keys(content)
                    driver.switch_to.default_content()
                    return True
                driver.switch_to.default_content()
            except Exception:
                driver.switch_to.default_content()
        return False
