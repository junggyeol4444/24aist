"""디스코드 공지 — 가장 안전하고 쉬움 (5-1).

봇 토큰으로 디스코드 REST API 에 메시지를 직접 POST 한다. 단발성 공지엔
게이트웨이(상시 연결)가 필요 없어 이 방식이 가볍고 안정적이다.
(봇 생성·토큰 발급·서버 초대 과정은 OPERATOR 문서 참고. 토큰은 .env)

역할 멘션: content 에 <@&role_id> 를 넣고 allowed_mentions 로 허용.
requests 지연 import, 호출은 asyncio.to_thread 로 감싼다.
"""

import asyncio
import logging
from pathlib import Path
from typing import Optional

from ..config import DiscordAnnounce
from .base import Announcer
from .retry import post_with_retry

log = logging.getLogger("aist.announce.discord")

_API = "https://discord.com/api/v10"


class DiscordAnnouncer(Announcer):
    name = "discord"

    def __init__(self, cfg: DiscordAnnounce, bot_token: str):
        self.cfg = cfg
        self.token = bot_token

    async def post(self, text: str, *, title: str = "") -> bool:
        if not self.cfg.enabled:
            return False
        if not self.token or not self.cfg.channel_id:
            log.warning("디스코드 토큰/채널ID 미설정 → 공지 생략")
            return False
        if not self._token_ok():
            return False
        payload = self.build_payload(text, title)
        return await asyncio.to_thread(self._post_sync, payload)

    def _token_ok(self) -> bool:
        """토큰이 HTTP 헤더에 실릴 수 있는 값인지.

        헤더는 latin-1 로만 보낼 수 있다. 토큰에 한글이나 특수문자가 섞이면
        (메모장에서 라벨까지 같이 붙여넣는 실수가 흔하다) 요청이 나가지도
        못하고 "'latin-1' codec can't encode characters" 만 세 번 반복된다.
        운영자가 그 메시지로 고칠 방법은 없다.
        """
        try:
            self.token.encode("latin-1")
        except UnicodeEncodeError:
            log.error("디스코드 토큰에 보낼 수 없는 문자가 섞여 있습니다"
                      "(한글·따옴표 등) — .env 의 DISCORD_BOT_TOKEN 을 "
                      "토큰 값만 남도록 다시 붙여넣으세요. 공지는 건너뜁니다.")
            return False
        return True

    def build_payload(self, text: str, title: str = "") -> dict:
        """게시 페이로드 구성 — 일반 텍스트 or 임베드(카드형)+이미지."""
        mention = f"<@&{self.cfg.mention_role_id}>" if self.cfg.mention_role_id else ""
        allowed = ({"roles": [str(self.cfg.mention_role_id)]}
                   if self.cfg.mention_role_id else {"parse": []})

        if not self.cfg.use_embed:
            content = f"{mention}\n{text}" if mention else text
            return {"content": content[:2000], "allowed_mentions": allowed}

        embed = {
            "title": (title or "방송 공지")[:256],
            "description": text[:4000],
            "color": self.cfg.embed_color,
        }
        if self.cfg.image_path:
            # 로컬 파일 첨부 → 임베드가 첨부 파일을 이미지로 사용
            fname = Path(self.cfg.image_path).name
            embed["image"] = {"url": f"attachment://{fname}"}
        elif self.cfg.image_url:
            embed["image"] = {"url": self.cfg.image_url}
        return {"content": mention, "embeds": [embed], "allowed_mentions": allowed}

    def _post_sync(self, payload: dict) -> bool:
        """한 번 실패가 곧 '공지 없음' 이 되지 않게 짧게 재시도한다."""
        try:
            import requests  # noqa: F401 - 미설치 확인용
        except ImportError:
            log.error("requests 미설치: `pip install requests`")
            return False
        if not self._token_ok():
            return False
        return post_with_retry(lambda: self._post_once(payload), what="디스코드 공지")

    def _post_once(self, payload: dict):
        """(성공여부, 상태코드, 사유). 상태코드 None 이면 네트워크 예외."""
        import requests
        url = f"{_API}/channels/{self.cfg.channel_id}/messages"
        headers = {"Authorization": f"Bot {self.token}"}
        try:
            image_path = self.cfg.image_path
            if self.cfg.use_embed and image_path and Path(image_path).exists():
                # 이미지 파일 첨부는 multipart(payload_json + files)
                import json as _json
                with Path(image_path).open("rb") as fh:
                    r = requests.post(
                        url, headers=headers,
                        data={"payload_json": _json.dumps(payload, ensure_ascii=False)},
                        files={"files[0]": (Path(image_path).name, fh)},
                        timeout=20,
                    )
            else:
                r = requests.post(url, headers={**headers, "Content-Type": "application/json"},
                                  json=payload, timeout=15)
            if r.status_code in (200, 201):
                log.info("디스코드 공지 게시 완료")
                return True, r.status_code, ""
            return False, r.status_code, r.text[:200]
        except Exception as e:  # noqa: BLE001 - 네트워크 사유 다양
            return False, None, str(e)
