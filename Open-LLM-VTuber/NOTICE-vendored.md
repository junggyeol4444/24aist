# Vendored & 개조 안내 (Open-LLM-VTuber)

이 디렉터리는 오픈소스 **Open-LLM-VTuber** 를 이 저장소에 포함(vendoring)한
복사본입니다. 이 자동화 레이어(24aist)의 방송 코어로 쓰며, 여기서 직접
개조합니다.

- 출처: https://github.com/Open-LLM-VTuber/Open-LLM-VTuber
- 라이선스: MIT (원본 `LICENSE` 유지. Copyright (c) 2025 Yi-Ting Chiu)
  - Live2D 샘플 모델은 `LICENSE-Live2D.md` 의 별도 약관을 따름.
- 받은 시점/브랜치: `main` (tarball 다운로드, git 히스토리는 제외)

## 포함하지 않은 것

- `frontend/` 의 컴파일 바이너리(웹 UI, wasm/onnx ~44MB) — 런타임 산출물이라
  커밋하지 않음. `scripts/fetch_frontend.sh` 로 받음.
- `backgrounds/` 의 기본 외 배경, 다운로드되는 ASR/TTS 모델, 캐시/로그 등
  런타임 데이터(원본 `.gitignore` 규칙 유지).

## 24aist 가 추가/개조한 것

- `conf.korean.yaml` — 한국어 실행 설정. 페르소나('별이') 주입,
  `tts_model: gpt_sovits_tts`, `gpt_sovits_tts.text_lang: ko`,
  `live2d_model_name: mao_pro`. 실행 시 `cp conf.korean.yaml conf.yaml` 후
  GPT-SoVITS 의 `api_url`/`ref_audio_path` 를 채워서 사용.
- `characters/kr_별이.yaml` — 한국어 캐릭터(alt) 설정.
- `src/open_llm_vtuber/conversations/tts_manager.py` — **[코드 개조]**
  TTS 출력 후처리 훅(`_post_process_audio`) 추가. 환경변수
  `AIST_TTS_POST_CMD` 가 설정되면 생성된 오디오 파일에 외부 명령(예: RVC
  2차 변조)을 실행(제자리 변환, 실패 시 원본 사용). 기획안 3-4.
  윈도우에서는 명령을 윈도우 방식으로 쪼갠다(POSIX 방식이면 `C:\rvc\x.bat`
  의 역슬래시가 사라져 매번 실패했다 — 윈도우 파이썬으로 확인). `.bat` 은
  `cmd /c` 로 돌리고, 명령이 실패 코드로 끝나면 경고를 남긴다.
  원본 업데이트 시 이 개조를 다시 적용해야 한다.

## 업데이트 방법

원본을 갱신하려면 `scripts/setup_openllm_vtuber.sh` 를 다시 실행하세요.
(우리가 추가한 `conf.korean.yaml`, `characters/kr_별이.yaml` 는 보존됩니다.)

> 코어의 동작·구조를 더 바꾸고 싶으면 `src/open_llm_vtuber/` 를 직접 수정하면
> 됩니다. 단, 원본 업데이트와 충돌할 수 있으니 변경은 작게 유지하고 기록하세요.

### 실제로 코어를 띄워 보고 고친 것 (2026-09)

가짜 서버가 아니라 이 코어를 직접 실행해서 확인한 것들이다.

1. **`avatars/`, `mcp_servers.json` 이 없어 코어가 시작조차 못 했다.**
   둘 다 원본 `.gitignore` 에 걸려 있어 받은 저장소에는 존재하지 않는데,
   코어는 시작할 때 둘 다 요구한다(`StaticFiles(directory="avatars")`,
   `ServerRegistry`). 없으면 파이썬 예외를 뱉고 그대로 죽는다 — 운영자에게는
   창이 깜빡이고 사라지는 것으로 보인다. 빈 `avatars/`(.gitkeep)와 빈
   `mcp_servers.json` 을 포함하고, `.gitignore` 에 예외를 뒀다.

2. **프록시가 무음 payload 에서 터져 방송이 멎었다.**
   `proxy_handler.broadcast_to_clients` 가 로그를 만들 때
   `len(message.get('audio', ''))` 를 부르는데, TTS 가 실패하거나 무음 표시일
   때 `audio` 는 `None` 이다. `len(None)` 이 터지면서 그 메시지가 **어떤
   클라이언트에게도 전달되지 않았고**, 웹UI 가 재생 완료를 못 보내니 코어는
   대화를 영영 끝내지 못했다(그 뒤로 방송인이 한 마디도 못 한다).
   `message.get('audio') or ''` 로 고쳤다.

3. **`system_config.enable_proxy: true`.**
   `/proxy-ws` 가 열려야 웹UI 와 방송 자동화가 같은 대화에 물린다.
   꺼져 있으면 AI 의 목소리·자막이 채팅을 넣은 쪽으로만 가서 OBS 화면에는
   아무것도 안 나온다.

4. **음성인식 엔진을 받을 게 없는 것으로 바꿨다.**
   이 방송은 마이크를 안 쓰는데(입력은 채팅 글), 코어는 시작할 때 음성인식을
   무조건 하나 초기화한다. 기본값(`sherpa_onnx_asr`)은 첫 실행에서 모델 약
   1GB 를 내려받고 2GB 넘게 차지하며, 다운로드가 막히면 코어가 아예 안 뜬다.
   마이크를 쓰려면 `conf.yaml` 에서 되돌리면 된다.

5. **긴 방송에서 LLM 컨텍스트가 무한히 늘던 것.**
   `basic_memory_agent` 의 대화 기록에는 상한이 없어서, 매 응답마다 지금까지의
   모든 대화를 LLM 에 다시 보낸다. 실제로 재보니 채팅 30건에 LLM 이 받는
   메시지가 60개까지 늘었고 계속 증가했다 — 몇 시간짜리 방송에서는 갈수록
   느려지다가 컨텍스트 한도에서 응답이 끊긴다.
   `max_memory_messages` 설정(0 이면 원래대로 무제한)을 추가하고
   `conf.korean.yaml` 에서 40 으로 둔다. 같은 조건에서 42개로 평평해졌다.
   시스템 프롬프트(페르소나)는 이 기록에 들어있지 않아 잘려도 캐릭터는 그대로다.

6. **대화 기록 파일(`chat_history/`)이 끝없이 커지며 코어를 멈췄다.**
   `store_message` 는 메시지 하나마다 기록 파일 전체를 읽고 다시 쓴다.
   웹UI 가 새로고침되지 않으면(무인 운영에서 OBS 는 몇 주씩 켜져 있다) 한
   파일이 계속 커진다. 재보니 2만 개(약 하루)에 저장 1회 0.12초, 14만 개에
   0.86초였고, 한 턴에 두 번씩 코어의 이벤트 루프를 멈춘다. 게다가 원본을
   열어 바로 쓰기 때문에, 디스크가 차서 쓰기가 실패하면 원본이 0바이트로
   잘렸다. `chat_history_manager.py` 에서 파일당 `MAX_HISTORY_MESSAGES`
   (2000개, 약 0.4MB, 저장 11ms)까지만 남기고, 임시 파일에 쓴 뒤 바꿔
   끼운다. 오래된 대화는 방송 자동화의 트랜스크립트에 전부 남는다.
