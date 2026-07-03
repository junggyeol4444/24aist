# 연결 가이드 — 코어 / TTS / OBS / 오디오 / 24시간 서버화

이 자동화 레이어(aist)가 어떻게 Open-LLM-VTuber 및 주변 도구와 붙는지
설명합니다. GPU 가 있는 운영자 환경(집 GPU PC 또는 GPU 클라우드)에서
진행하세요.

## 1. 방송 코어 — Open-LLM-VTuber (저장소에 포함됨)

방송 코어는 `Open-LLM-VTuber/` 에 vendoring 되어 있습니다(개조 대상). 받을
필요 없이 셋업만 하면 됩니다.

```bash
bash scripts/setup_openllm_vtuber.sh    # 프론트엔드 받기 + uv sync + conf 적용
# 페르소나를 바꾸면 재주입:
aist build-persona --conf Open-LLM-VTuber/conf.yaml --live2d <모델명>
```

- 무엇이 포함/제외됐는지: `Open-LLM-VTuber/NOTICE-vendored.md`
- 한국어 개조 설정: `Open-LLM-VTuber/conf.korean.yaml`
  (셋업 시 `conf.yaml` 로 복사됨)
- 웹 UI(프론트엔드 바이너리)는 `scripts/fetch_frontend.sh` 로 받음(커밋 제외).

`conf.yaml` 에서 운영자가 채울 핵심 키:

- `character_config.persona_prompt` — `aist build-persona` 가 주입(개조). 직접
  수정도 가능.
- `character_config.agent_config.llm_configs` — LLM 제공자/키(품질 우선이면
  클라우드 API, 비용 절감이면 로컬 Ollama).
- `character_config.tts_config.tts_model: gpt_sovits_tts` — `build-persona` 가
  설정. 아래 `gpt_sovits_tts.api_url`, `ref_audio_path`, `prompt_text`,
  `text_lang: ko` 를 채운다.
- `character_config.live2d_model_name` — 아바타 모델.
- `system_config.host/port` — 기본 `localhost:12393`. 이 값이 `config.yaml`
  의 `vtuber.ws_url` 과 일치해야 한다(`ws://<host>:<port>/client-ws`).

코어를 단독 실행해 "AI 가 말하고 아바타가 움직이는지" 먼저 확인(1단계).

### 브릿지가 코어로 보내는 것

`aist/vtuber_bridge.py` 는 코어의 WebSocket(`/client-ws`)에 JSON 을 보냅니다:

| 보내는 메시지 | 효과 |
|----------------|------|
| `{"type":"text-input","text":"[닉] 채팅내용"}` | AI 가 그 입력에 반응 |
| `{"type":"ai-speak-signal"}` | 혼잣말(능동 발화) 트리거 |
| `{"type":"interrupt-signal","text":""}` | 현재 발화 끼어들기 |

채팅 한 줄이 들어오면 그대로 `text-input` 으로 흘려보내, 코어의
LLM+페르소나가 대답을 만들고 TTS+Live2D 로 출력합니다. **여기서 채팅을
선별하거나 딜레이를 주지 않습니다.**

## 2. 한국어 목소리 — GPT-SoVITS

1. [GPT-SoVITS](https://github.com/RVC-Boss/GPT-SoVITS) 를 설치하고 API 서버를
   띄운다(보통 `http://127.0.0.1:9880`).
2. 본인/동의/라이선스 음성 1분 내외로 클로닝, 레퍼런스 오디오 준비.
3. 코어 `conf.yaml` 의 `gpt_sovits_tts.api_url`, `ref_audio_path`,
   `prompt_text`, `text_lang: ko` 채우기.
4. 톤을 더 다듬고 싶으면 **RVC 2차 변조**(기획안 3-4): 코어에 후처리 훅을
   개조해 뒀다. 환경변수 하나로 켠다 —
   ```bash
   # {in} 이 TTS 오디오 파일 경로로 치환됨. 명령은 제자리(in-place) 변환.
   export AIST_TTS_POST_CMD="bash /path/to/rvc_convert.sh {in}"
   ```
   RVC 프로젝트의 추론 CLI 를 감싼 스크립트를 지정하면 모든 TTS 출력이
   송출 전에 변조된다. 실패하면 원본 오디오로 방송은 계속(best-effort).
   개조 위치: `Open-LLM-VTuber/src/.../tts_manager.py` (`NOTICE-vendored.md` 참고)

> 법적 주의: 실존 인물(연예인·지인) 무단 클로닝은 금지. 본인 목소리거나
> 동의/라이선스 받은 음성만.

## 3. OBS + 가상 오디오 (3단계)

- OBS 에서 **obs-websocket** 활성화(도구 → WebSocket 서버 설정). 포트·비밀번호를
  `config.yaml` 의 `obs.*` 와 `.env` 의 `OBS_PASSWORD` 에 맞춘다.
- 코어의 아바타 창을 OBS 소스로 캡처(윈도우 캡처/브라우저 소스).
  **중요: 웹UI 전체가 아니라 아바타 영역만 캡처(크롭)할 것.** 자막·입력
  텍스트(귓속말/채팅 원문)가 방송 화면에 노출되면 안 된다.
- TTS 음성을 OBS 로 보내려면 가상 오디오 케이블(Windows: VB-CABLE, mac:
  BlackHole)을 깔고, 코어/시스템 출력 → 케이블 → OBS 오디오 입력으로 연결.
- 테스트 단계에선 `obs.start_stream: false` 로 두고 OBS 스트림은 수동으로
  켜며 확인 → 익숙해지면 `true` 로.

연결 점검:
```bash
aist check                  # 설정·키 상태
aist broadcast-now          # 코어·OBS·채팅 실제 연결 (비공개 테스트 권장)
```

## 4. 플랫폼 채팅 (귀) — 6개 지원 + 동출

설정: `config.yaml` 의 `platform`(단일) 또는 `platforms`(동출, 여러 개) +
`chat.<플랫폼>` 식별자. 토큰/키는 `.env`. 의존성: `pip install -e ".[platforms]"`.

| 플랫폼 | 식별자 | 토큰 | 비고 |
|--------|--------|------|------|
| **트위치** | `chat.twitch.channel` | 선택(없으면 익명 읽기) | IRC WebSocket, 바로 동작 |
| **유튜브** | `chat.youtube.video_id` | — | pytchat. 영상 ID 는 매 방송 바뀜 |
| **치지직** | `chat.chzzk.channel_id` | — | 비공식 WS. 공개방송 읽기 OK |
| **SOOP** | `chat.soop.bj_id` | — | 비공식 WS. ※ 첫 실 테스트로 필드 보정 필요할 수 있음 |
| **Kick** | `chat.kick.channel` | — | Pusher WS. Cloudflare 차단 시 chatroom_id 직접 지정 |
| **트위캐스팅** | `chat.twitcasting.user_id` | 필수(OAuth2) | 공식 API 코멘트 폴링 |

각 ChatMessage 에는 `platform` 필드가 있어, 코어/AI 가 어느 플랫폼에서 온
채팅인지 구분할 수 있습니다. 모든 플랫폼에서 **채팅을 선별 없이 전부**
코어로 흘려보냅니다(절대 원칙).

### 동출(동시 송출) — 채팅 수집 vs 영상 출력

- **채팅 수집(이 레이어가 처리)**: `platforms: [twitch, chzzk, kick, ...]` 로
  두면 `MultiChatSource` 가 여러 플랫폼 채팅을 하나로 합쳐 코어로 보냅니다.
  여러 방송의 시청자가 한 화면에서 같이 대화하는 효과.
- **영상 출력(다중 RTMP)**: 한 OBS 화면을 여러 플랫폼에 동시 송출하려면
  **obs-multi-rtmp** 같은 플러그인이 필요합니다(추가 인코더 출력이 필요해
  obs-websocket 단독으론 불가). 플러그인이 있다는 가정하에 우리 코드가
  `config.yaml` 의 `obs.simulcast` 로 이를 제어합니다:
  - `mode: plugin_autostart` (기본): 플러그인의 "OBS 스트림 시작 시 함께 시작"
    옵션을 켜두면, 우리의 `OBS 스트림 시작` 한 번이 추가 RTMP 출력까지 함께
    켭니다(추가 호출 없음).
  - `mode: vendor`: obs-websocket **vendor 요청**으로 플러그인 전체 시작/종료를
    직접 호출합니다(`vendor_name`/`start_request`/`stop_request`). 플러그인
    빌드가 vendor 요청을 지원할 때 사용하고, 요청명은 플러그인 문서에 맞춰
    조정합니다. 실패해도 본 방송은 계속됩니다(best-effort).
  - 대안: Restream.io 등 리스트림 서비스로 한 번 보내 여러 곳에 분배(이 경우
    OBS 는 단일 출력이라 `simulcast.enabled: false` 로 두면 됨).
  - `simulcast.targets` 는 참고/공지용 목록입니다(실제 스트림 키는 플러그인에
    설정 권장). 공지 링크는 `announce.link` 에 리스트림/대표 링크를 두거나
    디스코드 공지에 여러 링크를 넣으세요.

## 5. 24시간 서버화 + 자동 재시작 (7단계)

실파일이 준비되어 있다 — 리눅스에서 한 줄로 설치:

```bash
bash deploy/install.sh                    # aist 를 systemd 서비스로
bash deploy/install.sh --with-minecraft   # 게임 사이드카까지 서비스로
```

- 죽으면 5초 후 자동 재시작(`Restart=always`).
- 로그: `journalctl -u aist -f` + 회전 파일 `data/logs/aist.log`.
- **사고 발언 점검**: 방송별 트랜스크립트 `data/logs/transcripts/*.jsonl` 에
  시청자 채팅과 **AI 가 실제로 말한 문장 전부**가 남는다.
- **다시보기 학습**: 방송이 끝날 때마다 `data/reports/*.md` 리포트가 자동
  생성된다(누가 왔는지/단골/슈퍼챗/AI 발화 전문/다음 방송). `aist report`
  로 재생성 가능. 하루 5~10분 점검은 이 파일 하나로.
- 코어(Open-LLM-VTuber)·GPT-SoVITS·OBS 도 각각 자동 시작되게 설정(그래픽
  세션이 필요한 OBS 는 자동로그인+시작프로그램이 현실적).
- 며칠 돌리며 터지는 부분은 로그를 붙여 Claude Code 와 함께 해결.

## 6. 게임 플레이 (8단계, 선택) — 마인크래프트

`game/minecraft/README.md` 참고. 요약:

```bash
cd game/minecraft && npm install
MC_HOST=127.0.0.1 MC_USERNAME=aist_bot node bot.js   # 사이드카
# config.yaml: game.enabled: true
```

mineflayer 봇이 게임 이벤트(죽음/체력위험/튕김/게임채팅)를 WebSocket 으로
중계하고, `aist/game/minecraft.py` 가 상황 큐를 코어로 보내 페르소나가
캐릭터답게 반응한다("어 죽었다" 등 — 정확한 말은 페르소나가 정함).
게임 중에도 시청자 채팅 소통은 그대로 유지된다.

## 7. 공지 LLM 비용 0 — 로컬 Ollama

```yaml
llm:
  provider: "ollama"
  model: "llama3.1"        # ollama pull llama3.1
  # base_url 비우면 http://127.0.0.1:11434/v1
```

Ollama 가 꺼져 있으면 공지는 오프라인 변주 풀로 자동 대체된다(방송은 계속).

## 비용 메모

- LLM·TTS 를 24시간 클라우드로 돌리면 비용 누적 → 안정화 후 로컬(Ollama +
  GPT-SoVITS)로 전환하면 매달 비용이 크게 준다(전기세 감수).
- `config.yaml` 의 `llm.provider` 를 `openai`↔`dummy`↔로컬(OpenAI 호환
  `base_url`)로 바꿔 공지용 LLM 비용도 조절.
