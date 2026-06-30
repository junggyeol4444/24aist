"""platform 설정에 따라 알맞은 ChatSource 를 만든다."""

from ..config import Config
from .base import ChatSource


def make_chat_source(cfg: Config) -> ChatSource:
    platform = cfg.platform
    s = cfg.secrets
    if platform == "twitch":
        from .twitch import TwitchChat
        return TwitchChat(
            channel=s.twitch_channel,
            oauth_token=s.twitch_oauth_token,
            nick=s.twitch_nick,
        )
    if platform == "youtube":
        from .youtube import YouTubeChat
        # 유튜브는 라이브 영상 ID 가 매 방송 달라진다 → .env 의 채널 필드 대신
        # 별도 환경변수(YOUTUBE_VIDEO_ID)나 실행 인자로 주는 것을 권장.
        import os
        video_id = os.environ.get("YOUTUBE_VIDEO_ID", "")
        return YouTubeChat(video_id=video_id)
    if platform == "chzzk":
        from .chzzk import ChzzkChat
        return ChzzkChat(channel_id=s.chzzk_channel_id)
    raise ValueError(f"알 수 없는 platform: {platform!r}")
