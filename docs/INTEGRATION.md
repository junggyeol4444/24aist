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
4. 톤을 더 다듬고 싶으면 RVC 2차 변환 추가(선택).

> 법적 주의: 실존 인물(연예인·지인) 무단 클로닝은 금지. 본인 목소리거나
> 동의/라이선스 받은 음성만.

## 3. OBS + 가상 오디오 (3단계)

- OBS 에서 **obs-websocket** 활성화(도구 → WebSocket 서버 설정). 포트·비밀번호를
  `config.yaml` 의 `obs.*` 와 `.env` 의 `OBS_PASSWORD` 에 맞춘다.
- 코어의 아바타 창을 OBS 소스로 캡처(윈도우 캡처/브라우저 소스).
- TTS 음성을 OBS 로 보내려면 가상 오디오 케이블(Windows: VB-CABLE, mac:
  BlackHole)을 깔고, 코어/시스템 출력 → 케이블 → OBS 오디오 입력으로 연결.
- 테스트 단계에선 `obs.start_stream: false` 로 두고 OBS 스트림은 수동으로
  켜며 확인 → 익숙해지면 `true` 로.

연결 점검:
```bash
aist check                  # 설정·키 상태
aist broadcast-now          # 코어·OBS·채팅 실제 연결 (비공개 테스트 권장)
```

## 4. 플랫폼 채팅 (귀)

- **트위치**: `.env` 의 `TWITCH_CHANNEL`(필수), `TWITCH_OAUTH_TOKEN`/`TWITCH_NICK`
  (없으면 익명 읽기). 바로 동작.
- **유튜브**: 라이브 영상 ID 가 매 방송 바뀌므로 `YOUTUBE_VIDEO_ID` 환경변수로
  전달. `pip install pytchat` 필요.
- **치지직(chzzk)**: 공식 채팅 API 가 없어 통합 지점만 둠
  (`aist/chat/chzzk.py` 상단 주석의 절차대로 채움).

## 5. 24시간 서버화 + 자동 재시작 (7단계)

리눅스 systemd 예시(`/etc/systemd/system/aist.service`):

```ini
[Unit]
Description=AI Streamer (aist)
After=network-online.target

[Service]
WorkingDirectory=/home/youruser/24aist
ExecStart=/home/youruser/24aist/.venv/bin/aist run
Restart=always
RestartSec=5
# 코어/OBS 가 같은 머신이면 그래픽 세션 필요 — 환경에 맞게 조정

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable --now aist
journalctl -u aist -f        # 로그 보기 (사고 발언·에러 점검)
```

- 코어(Open-LLM-VTuber)·GPT-SoVITS·OBS 도 각각 자동 시작/재시작되게 설정.
- 며칠 돌리며 메모리 누수·API 끊김 등 터지는 부분을 잡는다(로그를 붙여
  Claude Code 와 함께 해결).

## 비용 메모

- LLM·TTS 를 24시간 클라우드로 돌리면 비용 누적 → 안정화 후 로컬(Ollama +
  GPT-SoVITS)로 전환하면 매달 비용이 크게 준다(전기세 감수).
- `config.yaml` 의 `llm.provider` 를 `openai`↔`dummy`↔로컬(OpenAI 호환
  `base_url`)로 바꿔 공지용 LLM 비용도 조절.
