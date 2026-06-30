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

## 업데이트 방법

원본을 갱신하려면 `scripts/setup_openllm_vtuber.sh` 를 다시 실행하세요.
(우리가 추가한 `conf.korean.yaml`, `characters/kr_별이.yaml` 는 보존됩니다.)

> 코어의 동작·구조를 더 바꾸고 싶으면 `src/open_llm_vtuber/` 를 직접 수정하면
> 됩니다. 단, 원본 업데이트와 충돌할 수 있으니 변경은 작게 유지하고 기록하세요.
