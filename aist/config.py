"""설정 로딩 — config.yaml 을 읽어 타입이 있는 dataclass 로 변환한다.

설계 원칙:
- 운영자가 만지는 모든 값은 YAML 에 있다. 코드에 박지 않는다.
- 비밀(토큰/키)은 YAML 이 아니라 환경변수(.env)에서 읽는다.
- 빠진 키는 아래 정의된 기본값으로 채워, 부분 설정만 줘도 동작한다.
- 기본값 자체가 기획안의 "디폴트"를 반영한다(다 반응/딜레이0/변주0 등).
"""

import os
from dataclasses import dataclass, field, fields, is_dataclass
from pathlib import Path
from typing import Any, Dict, List, Union

import yaml


# --------------------------------------------------------------------------- #
# 섹션별 dataclass. 기본값 = 기획안의 "단순한 디폴트".
# --------------------------------------------------------------------------- #
@dataclass
class VTuberConfig:
    """Open-LLM-VTuber 연결(두뇌+입+얼굴+귀)."""
    ws_url: str = "ws://127.0.0.1:12393/client-ws"
    connect_timeout_sec: float = 10.0
    reconnect: bool = True


@dataclass
class ObsConfig:
    host: str = "127.0.0.1"
    port: int = 4455
    password: str = ""          # 비우면 .env 의 OBS_PASSWORD 사용
    start_stream: bool = True    # False 면 OBS 시작은 운영자 수동(테스트 단계)


@dataclass
class SchedulerConfig:
    """시작 자동화(심장박동) — 5단계."""
    enabled: bool = True
    timezone: str = "Asia/Seoul"
    # 요일별 시작 시각. 빈 리스트면 그 요일은 휴방(쉬는 날).
    weekly: Dict[str, List[str]] = field(default_factory=lambda: {
        "mon": ["19:00"], "tue": ["19:00"], "wed": ["19:00"],
        "thu": ["19:00"], "fri": ["20:00"], "sat": ["20:00"], "sun": [],
    })
    # 랜덤 변주(선택). 0 이면 정확히 그 시각. 강제 아님 — 운영자가 정한다.
    start_jitter_min: int = 0
    jitter_mode: str = "after"   # after(늦게만) | symmetric(앞뒤)


@dataclass
class FloodHandling:
    # 채팅 폭주 처리: 기본 off. 실제로 폭주가 생긴 뒤 운영자가 켠다.
    enabled: bool = False
    max_per_window: int = 0
    window_sec: int = 10


@dataclass
class BroadcastConfig:
    """방송 진행(핵심 루프) — 채팅 처리 기본 방침을 담는다."""
    # 절대 원칙: 기본은 다 읽고 다 반응, 자연스러운 속도.
    respond_to_all_chat: bool = True
    artificial_delay_sec: float = 0.0
    idle_proactive_speak: bool = True
    idle_seconds_before_proactive: int = 45
    flood_handling: FloodHandling = field(default_factory=FloodHandling)


@dataclass
class ChatLow:
    # 채팅 저조 종료: 기본 off (채팅 없어도 계속 방송하길 원할 수 있음).
    enabled: bool = False
    quiet_minutes: int = 20


@dataclass
class WindDown:
    # 자연스러운 마무리(뚝 끄지 않음): 예고 → 인사 → 종료.
    enabled: bool = True
    pre_notice_minutes_before_end: int = 10
    closing_greeting: bool = True


@dataclass
class EndJudgeConfig:
    """종료 판단(감각) — 4단계. 값은 운영자가 조정."""
    max_minutes: int = 180        # 약 3시간이면 마무리 (가장 기본)
    min_minutes: int = 60         # 최소 1시간 보장
    scheduled_end_hhmm: str = ""  # 예: "00:00". 빈 문자열이면 미사용
    chat_low: ChatLow = field(default_factory=ChatLow)
    end_jitter_min: int = 0       # 종료 시각 랜덤 변주(선택). 0 이면 정확히.
    wind_down: WindDown = field(default_factory=WindDown)


@dataclass
class DiscordAnnounce:
    enabled: bool = True
    channel_id: int = 0
    mention_role_id: int = 0      # 0 이면 멘션 없음


@dataclass
class NaverCafeAnnounce:
    enabled: bool = False
    cafe_id: str = ""
    menu_id: str = ""
    use_official_api: bool = True       # 1순위 공식 API
    use_selenium_fallback: bool = False  # 보조. 본인 카페 + 저빈도만.


@dataclass
class AnnounceConfig:
    """공지 자동화 — 6단계."""
    on_start: bool = True
    on_end: bool = True
    avoid_late_night: bool = True
    late_night_window: List[str] = field(default_factory=lambda: ["01:00", "08:00"])
    style: str = "varied"               # varied | fixed
    fixed_start_template: str = "방송 시작했어요! {link}"
    fixed_end_template: str = "오늘 방송 끝! 다음에 또 봐요."
    link: str = ""
    discord: DiscordAnnounce = field(default_factory=DiscordAnnounce)
    naver_cafe: NaverCafeAnnounce = field(default_factory=NaverCafeAnnounce)


# --------------------------------------------------------------------------- #
# 채팅 수집 (귀) — 플랫폼별 식별자. 토큰/비밀은 .env(Secrets) 에.
# 동출(동시 송출)이면 platforms 에 여러 개를 넣고, 각 플랫폼 식별자를 채운다.
# --------------------------------------------------------------------------- #
VALID_PLATFORMS = ("twitch", "youtube", "chzzk", "soop", "kick", "twitcasting")


@dataclass
class TwitchChatCfg:
    channel: str = ""        # 비우면 .env TWITCH_CHANNEL


@dataclass
class YouTubeChatCfg:
    video_id: str = ""       # 라이브 영상 ID. 비우면 .env YOUTUBE_VIDEO_ID


@dataclass
class ChzzkChatCfg:
    channel_id: str = ""     # 치지직 채널 ID. 비우면 .env CHZZK_CHANNEL_ID


@dataclass
class SoopChatCfg:
    bj_id: str = ""          # SOOP(아프리카TV) BJ 아이디(스트리머 ID)


@dataclass
class KickChatCfg:
    channel: str = ""        # kick.com 채널 슬러그(주소의 이름)


@dataclass
class TwitcastingChatCfg:
    user_id: str = ""        # 트위캐스팅 사용자 ID(screen id)


@dataclass
class ChatConfig:
    twitch: TwitchChatCfg = field(default_factory=TwitchChatCfg)
    youtube: YouTubeChatCfg = field(default_factory=YouTubeChatCfg)
    chzzk: ChzzkChatCfg = field(default_factory=ChzzkChatCfg)
    soop: SoopChatCfg = field(default_factory=SoopChatCfg)
    kick: KickChatCfg = field(default_factory=KickChatCfg)
    twitcasting: TwitcastingChatCfg = field(default_factory=TwitcastingChatCfg)


@dataclass
class LlmConfig:
    """공지 문구 생성용 LLM. 키는 .env 에서."""
    provider: str = "dummy"   # openai | anthropic | gemini | dummy
    model: str = "gpt-4o-mini"
    base_url: str = ""        # OpenAI 호환 엔드포인트면 지정
    temperature: float = 0.9
    max_tokens: int = 300


@dataclass
class MemoryConfig:
    backend: str = "json"     # json | chroma
    path: str = "data/memory"


@dataclass
class LoggingConfig:
    level: str = "INFO"
    dir: str = "data/logs"


@dataclass
class Secrets:
    """환경변수(.env)에서 읽는 비밀값. YAML 에 두지 않는다."""
    openai_api_key: str = ""
    anthropic_api_key: str = ""
    gemini_api_key: str = ""
    obs_password: str = ""
    discord_bot_token: str = ""
    twitch_oauth_token: str = ""
    twitch_nick: str = ""
    twitch_channel: str = ""
    naver_client_id: str = ""
    naver_client_secret: str = ""
    naver_access_token: str = ""
    naver_refresh_token: str = ""
    chzzk_channel_id: str = ""
    youtube_video_id: str = ""
    soop_bj_id: str = ""
    kick_channel: str = ""
    twitcasting_user_id: str = ""
    twitcasting_access_token: str = ""

    @classmethod
    def from_env(cls) -> "Secrets":
        g = os.environ.get
        return cls(
            openai_api_key=g("OPENAI_API_KEY", ""),
            anthropic_api_key=g("ANTHROPIC_API_KEY", ""),
            gemini_api_key=g("GEMINI_API_KEY", ""),
            obs_password=g("OBS_PASSWORD", ""),
            discord_bot_token=g("DISCORD_BOT_TOKEN", ""),
            twitch_oauth_token=g("TWITCH_OAUTH_TOKEN", ""),
            twitch_nick=g("TWITCH_NICK", ""),
            twitch_channel=g("TWITCH_CHANNEL", ""),
            naver_client_id=g("NAVER_CLIENT_ID", ""),
            naver_client_secret=g("NAVER_CLIENT_SECRET", ""),
            naver_access_token=g("NAVER_ACCESS_TOKEN", ""),
            naver_refresh_token=g("NAVER_REFRESH_TOKEN", ""),
            chzzk_channel_id=g("CHZZK_CHANNEL_ID", ""),
            youtube_video_id=g("YOUTUBE_VIDEO_ID", ""),
            soop_bj_id=g("SOOP_BJ_ID", ""),
            kick_channel=g("KICK_CHANNEL", ""),
            twitcasting_user_id=g("TWITCASTING_USER_ID", ""),
            twitcasting_access_token=g("TWITCASTING_ACCESS_TOKEN", ""),
        )


@dataclass
class Config:
    # 단일 플랫폼. 동출(동시 송출)이면 platforms 에 여러 개를 넣는다.
    platform: str = "twitch"   # twitch|youtube|chzzk|soop|kick|twitcasting
    platforms: List[str] = field(default_factory=list)  # 비우면 platform 단일 사용
    chat: ChatConfig = field(default_factory=ChatConfig)
    vtuber: VTuberConfig = field(default_factory=VTuberConfig)
    obs: ObsConfig = field(default_factory=ObsConfig)
    scheduler: SchedulerConfig = field(default_factory=SchedulerConfig)
    broadcast: BroadcastConfig = field(default_factory=BroadcastConfig)
    end_judge: EndJudgeConfig = field(default_factory=EndJudgeConfig)
    announce: AnnounceConfig = field(default_factory=AnnounceConfig)
    llm: LlmConfig = field(default_factory=LlmConfig)
    memory: MemoryConfig = field(default_factory=MemoryConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    secrets: Secrets = field(default_factory=Secrets)

    def active_platforms(self) -> List[str]:
        """이번 방송에서 채팅을 수집할 플랫폼 목록(동출이면 여러 개)."""
        return list(self.platforms) if self.platforms else [self.platform]

    def resolve_secrets(self) -> None:
        """비밀값이 YAML 에 비어있으면 .env 값으로 채운다(OBS 비번 등)."""
        if not self.obs.password and self.secrets.obs_password:
            self.obs.password = self.secrets.obs_password


# --------------------------------------------------------------------------- #
# YAML(dict) → dataclass 재귀 변환. 모르는 키는 무시, 빠진 키는 기본값.
# --------------------------------------------------------------------------- #
def _build(cls, data: Any):
    if not is_dataclass(cls):
        return data
    if data is None:
        return cls()
    if not isinstance(data, dict):
        raise ConfigError(f"{cls.__name__} 섹션은 매핑(dict)이어야 합니다. 받은 값: {type(data).__name__}")
    kwargs: Dict[str, Any] = {}
    known = {f.name: f for f in fields(cls)}
    for key, f in known.items():
        if key not in data:
            continue  # 기본값 사용
        raw = data[key]
        ftype = f.type
        # 중첩 dataclass 처리
        if is_dataclass(ftype):
            kwargs[key] = _build(ftype, raw)
        else:
            kwargs[key] = raw
    return cls(**kwargs)


class ConfigError(Exception):
    pass


def load_config(path: Union[str, Path]) -> Config:
    """config.yaml 을 읽어 Config 로 만든다. 비밀은 .env(환경변수)에서 채운다."""
    p = Path(path)
    if not p.exists():
        raise ConfigError(
            f"설정 파일이 없습니다: {p}\n"
            f"config/config.example.yaml 을 복사해서 config.yaml 을 만드세요."
        )
    with p.open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}
    if not isinstance(raw, dict):
        raise ConfigError("config.yaml 최상위는 매핑(dict)이어야 합니다.")

    cfg = Config(
        platform=raw.get("platform", "twitch"),
        platforms=list(raw.get("platforms", []) or []),
        chat=_build(ChatConfig, raw.get("chat")),
        vtuber=_build(VTuberConfig, raw.get("vtuber")),
        obs=_build(ObsConfig, raw.get("obs")),
        scheduler=_build(SchedulerConfig, raw.get("scheduler")),
        broadcast=_build(BroadcastConfig, raw.get("broadcast")),
        end_judge=_build(EndJudgeConfig, raw.get("end_judge")),
        announce=_build(AnnounceConfig, raw.get("announce")),
        llm=_build(LlmConfig, raw.get("llm")),
        memory=_build(MemoryConfig, raw.get("memory")),
        logging=_build(LoggingConfig, raw.get("logging")),
        secrets=Secrets.from_env(),
    )
    cfg.resolve_secrets()
    _validate(cfg)
    return cfg


def _validate(cfg: Config) -> None:
    valid = "|".join(VALID_PLATFORMS)
    # 동출이면 platforms 를, 아니면 단일 platform 을 검증.
    targets = cfg.platforms if cfg.platforms else [cfg.platform]
    for p in targets:
        if p not in VALID_PLATFORMS:
            raise ConfigError(f"플랫폼은 {valid} 중 하나여야 합니다: {p!r}")
    ej = cfg.end_judge
    if ej.min_minutes > ej.max_minutes:
        raise ConfigError(
            f"end_judge.min_minutes({ej.min_minutes}) 가 max_minutes({ej.max_minutes}) 보다 큽니다."
        )
    if cfg.announce.style not in ("varied", "fixed"):
        raise ConfigError(f"announce.style 은 varied|fixed 여야 합니다: {cfg.announce.style!r}")
    if cfg.llm.provider not in ("openai", "anthropic", "gemini", "dummy"):
        raise ConfigError(f"llm.provider 가 올바르지 않습니다: {cfg.llm.provider!r}")
