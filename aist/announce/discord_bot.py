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
        payload = self.build_payload(text, title)
        return await asyncio.to_thread(self._post_sync, payload)

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
        try:
            import requests  # 지연 import
        except ImportError:
            log.error("requests 미설치: `pip install requests`")
            return False
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
                return True
            log.error("디스코드 공지 실패 (%s): %s", r.status_code, r.text[:300])
            return False
        except Exception as e:  # noqa: BLE001
            log.error("디스코드 공지 예외: %s", e)
            return False
