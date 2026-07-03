"""platform/platforms 설정에 따라 ChatSource 를 만든다.

- 단일 플랫폼이면 그 소스 하나를, 동출(platforms 가 여러 개)이면
  MultiChatSource 로 합쳐서 돌려준다.
- 식별자는 config 의 chat.* 를 우선 쓰고, 비어있으면 .env(secrets) 로 보완.
"""

from ..config import Config
from .base import ChatSource


def make_single_source(platform: str, cfg: Config) -> ChatSource:
    s = cfg.secrets
    c = cfg.chat
    if platform == "twitch":
        from .twitch import TwitchChat
        return TwitchChat(
            channel=c.twitch.channel or s.twitch_channel,
            oauth_token=s.twitch_oauth_token, nick=s.twitch_nick,
        )
    if platform == "youtube":
        from .youtube import YouTubeChat
        return YouTubeChat(
            video_id=c.youtube.video_id or s.youtube_video_id,
            channel=c.youtube.channel,
        )
    if platform == "chzzk":
        from .chzzk import ChzzkChat
        return ChzzkChat(channel_id=c.chzzk.channel_id or s.chzzk_channel_id)
    if platform == "soop":
        from .soop import SoopChat
        return SoopChat(bj_id=c.soop.bj_id or s.soop_bj_id)
    if platform == "kick":
        from .kick import KickChat
        return KickChat(channel=c.kick.channel or s.kick_channel)
    if platform == "twitcasting":
        from .twitcasting import TwitcastingChat
        return TwitcastingChat(
            user_id=c.twitcasting.user_id or s.twitcasting_user_id,
            access_token=s.twitcasting_access_token,
        )
    raise ValueError(f"알 수 없는 platform: {platform!r}")


def make_chat_source(cfg: Config) -> ChatSource:
    platforms = cfg.active_platforms()
    sources = [make_single_source(p, cfg) for p in platforms]
    if len(sources) == 1:
        return sources[0]
    from .multi import MultiChatSource
    return MultiChatSource(sources)
