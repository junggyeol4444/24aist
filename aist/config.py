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
from typing import Any, Dict, List, Union, get_args, get_origin

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
class SimulcastTarget:
    name: str = ""     # 표시용 이름(예: "youtube")
    url: str = ""      # rtmp 서버 주소 (참고/공지용)
    key: str = ""      # 스트림 키 (참고용 — 실제 키는 플러그인에 설정 권장)


@dataclass
class SimulcastConfig:
    """영상 동출(다중 RTMP). obs-multi-rtmp 같은 플러그인이 있다는 가정.

    mode:
      - plugin_autostart: 플러그인의 "OBS 스트림 시작 시 함께 시작" 옵션을 켜두면,
        우리의 일반 스트림 시작이 추가 RTMP 출력까지 함께 켠다(추가 호출 없음).
      - vendor: obs-websocket vendor 요청으로 플러그인의 전체 시작/종료를 직접
        호출한다(플러그인 빌드가 vendor 요청을 지원할 때). 요청명은 플러그인
        문서에 맞춰 start_request/stop_request 로 조정.
    """
    enabled: bool = False
    mode: str = "plugin_autostart"       # plugin_autostart | vendor
    vendor_name: str = "obs-multi-rtmp"
    start_request: str = "StartAll"      # vendor 모드 요청명(플러그인에 맞게)
    stop_request: str = "StopAll"
    targets: List[SimulcastTarget] = field(default_factory=list)  # 참고/공지용


@dataclass
class ObsConfig:
    host: str = "127.0.0.1"
    port: int = 4455
    password: str = ""          # 비우면 .env 의 OBS_PASSWORD 사용
    start_stream: bool = True    # False 면 OBS 시작은 운영자 수동(테스트 단계)
    # OBS 프로그램 자동 실행(2-2③): 연결 실패 시 OBS 를 직접 켠다.
    launch_if_not_running: bool = False
    launch_command: str = ""     # 예: "obs --disable-shutdown-check" (경로는 환경마다)
    launch_wait_sec: int = 20    # 켠 뒤 연결될 때까지 기다리는 최대 시간
    simulcast: SimulcastConfig = field(default_factory=SimulcastConfig)


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
    """방송 진행(핵심 루프) — 채팅 처리 기본 방침을 담는다.

    채팅 처리는 '입 하나' 모델(운영자 지시): 말 안 하는 중이면 즉답,
    말하는 중이면 쌓아뒀다가 말이 끝나는 순간 전부 이어받는다.
    타이머/랜덤 없음. 채팅은 하나도 버리지 않는다(다 반응).
    """
    # 절대 원칙: 기본은 다 읽고 다 반응, 자연스러운 속도.
    respond_to_all_chat: bool = True
    artificial_delay_sec: float = 0.0
    # 워밍업 오프닝(4-1): 켜자마자 각 잡지 않고 세팅 확인하듯 가볍게 시작
    warmup_opening: bool = True
    # 코어의 말 끝(chain-end) 신호가 유실됐을 때 잠금 해제 폴백(초)
    core_busy_timeout_sec: float = 90.0
    # 혼잣말(눈치껏): 말하는 중엔 안 하고, 채팅 없이 혼잣말이 이어지면
    # 간격이 점점 길어진다(사람은 침묵을 매번 같은 간격으로 채우지 않음).
    idle_proactive_speak: bool = True
    idle_seconds_before_proactive: int = 45
    idle_backoff_multiplier: float = 1.7   # 연속 혼잣말마다 간격 배율
    idle_backoff_max_multiple: float = 8.0  # 간격 상한(기본값의 몇 배까지)
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
    # 눈치 종료(운영자 지시): 예정 시각이 돼도 바로 끊지 않고,
    # 말 안 하는 중 + 채팅이 잠깐 소강인 타이밍을 잡아 마무리한다.
    natural_pause_lull_sec: int = 8       # "소강"으로 볼 채팅 공백(초)
    max_overtime_minutes: int = 10        # 타이밍 못 잡아도 이 이상은 안 기다림


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
    use_embed: bool = False       # 카드형(임베드) 공지
    embed_color: int = 5793266    # 임베드 색 (기본: 디스코드 블루플)
    image_url: str = ""           # 임베드에 넣을 이미지 URL(선택)
    image_path: str = ""          # 로컬 이미지 첨부(선택, 파일 업로드)


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
    # 방송 시작 전 미리 공지(2-2② 기본 동선: 공지 → 방송 시작).
    # 사람도 방송 전에 미리 알린다 — 기본 30분 전. 0 이면 시작 시점에 게시.
    # (스케줄러 자동 모드에서 동작 — broadcast-now 는 즉시 시작이라 시작 시점 게시)
    pre_announce_minutes: int = 30
    avoid_late_night: bool = True
    late_night_window: List[str] = field(default_factory=lambda: ["01:00", "08:00"])
    style: str = "varied"               # varied | fixed
    fixed_start_template: str = "방송 시작했어요! {link}"
    fixed_end_template: str = "오늘 방송 끝! 다음에 또 봐요."
    link: str = ""
    history_size: int = 8               # 최근 쓴 문구 기억(반복 방지)
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
    # 완전 자동화용(권장): 채널 핸들(@이름) 또는 채널 ID(UC…)를 주면
    # 방송 시작 시 현재 라이브의 video_id 를 자동으로 찾는다.
    channel: str = ""


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
    """공지 문구 생성용 LLM. 키는 .env 에서.

    ollama: 로컬 LLM(비용 0). Ollama 의 OpenAI 호환 엔드포인트를 쓴다.
    base_url 비우면 http://127.0.0.1:11434/v1 기본.
    """
    provider: str = "dummy"   # openai | anthropic | gemini | ollama | dummy
    model: str = "gpt-4o-mini"
    base_url: str = ""        # OpenAI 호환 엔드포인트면 지정 (ollama 포함)
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
    file_log: bool = True          # 회전 파일 로그(dir/aist.log)
    transcript: bool = True        # 방송별 채팅+AI발화 JSONL (사고발언 점검)
    auto_report: bool = True       # 방송 종료 시 리포트 자동 생성
    reports_dir: str = "data/reports"
    # 종료 후 컨텐츠 제작(2-2⑦): 하이라이트 후보(채팅 급증 구간)·제목 초안
    auto_content: bool = True
    content_dir: str = "data/content"


@dataclass
class GameConfig:
    """게임 플레이(8단계, 선택). 봇 API 연동이 쉬운 마인크래프트부터.

    mineflayer 사이드카(game/minecraft/bot.js)가 게임에 접속해 이벤트를
    WebSocket 으로 중계하고, 우리 GameFeed 가 그걸 AI 반응으로 잇는다.
    """
    enabled: bool = False
    type: str = "minecraft"                 # 현재 minecraft 만
    ws_url: str = "ws://127.0.0.1:8765"     # 사이드카 주소
    # 게임 내 채팅을 시청자 채팅처럼 AI 에게 전달할지
    forward_game_chat: bool = True
    # 어떤 이벤트에 반응할지 (사이드카가 보내는 event 이름)
    react_events: List[str] = field(default_factory=lambda: [
        "death", "respawn", "kicked", "health_low",
    ])


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
    naver_nid_aut: str = ""       # 카페 셀레늄용 로그인 쿠키(선택)
    naver_nid_ses: str = ""
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
            naver_nid_aut=g("NAVER_NID_AUT", ""),
            naver_nid_ses=g("NAVER_NID_SES", ""),
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
    game: GameConfig = field(default_factory=GameConfig)
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
        elif _is_dataclass_list(ftype) and isinstance(raw, list):
            item_cls = get_args(ftype)[0]
            kwargs[key] = [_build(item_cls, item) for item in raw]
        else:
            kwargs[key] = raw
    return cls(**kwargs)


def _is_dataclass_list(ftype) -> bool:
    """List[SomeDataclass] 형태인지."""
    if get_origin(ftype) not in (list, List):
        return False
    args = get_args(ftype)
    return bool(args) and is_dataclass(args[0])


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
        game=_build(GameConfig, raw.get("game")),
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
    if cfg.llm.provider not in ("openai", "anthropic", "gemini", "ollama", "dummy"):
        raise ConfigError(f"llm.provider 가 올바르지 않습니다: {cfg.llm.provider!r}")
    if cfg.game.enabled and cfg.game.type != "minecraft":
        raise ConfigError(f"game.type 은 현재 minecraft 만 지원합니다: {cfg.game.type!r}")
    if cfg.obs.simulcast.mode not in ("plugin_autostart", "vendor"):
        raise ConfigError(
            f"obs.simulcast.mode 는 plugin_autostart|vendor 여야 합니다: {cfg.obs.simulcast.mode!r}"
        )
    if cfg.memory.backend not in ("json", "chroma"):
        raise ConfigError(f"memory.backend 는 json|chroma 여야 합니다: {cfg.memory.backend!r}")
