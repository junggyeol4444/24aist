# 24aist — AI 방송인 자동화 레이어

사람 손 안 쓰고 24시간 자율로 운영되는, "사람처럼 느껴지는" AI 버추얼
방송인을 만들기 위한 **자동화 레이어**입니다. (기획안 3종 문서 기반 구현)

방송의 "두뇌·입·얼굴·귀"(LLM·TTS·Live2D·채팅)는 오픈소스
**[Open-LLM-VTuber](https://github.com/Open-LLM-VTuber/Open-LLM-VTuber)**
가 70%를 해결합니다. 이 저장소는 그 위에 올라가는 **나머지 30% — "손발 +
심장박동"**, 즉 직접 만들어야 하는 부분을 담습니다:

> 스케줄러 · 종료 판단 · OBS 제어 · 채팅 브릿지 · 공지봇(디스코드/네이버
> 카페) · 장기기억 · 이 모두를 지휘하는 **오케스트레이터**.

방송 코어(Open-LLM-VTuber)는 [`Open-LLM-VTuber/`](Open-LLM-VTuber/) 에
**포함(vendoring)되어 있어 바로 개조**할 수 있습니다. 한국어 개조 설정
([`conf.korean.yaml`](Open-LLM-VTuber/conf.korean.yaml))과 캐릭터
([`characters/kr_별이.yaml`](Open-LLM-VTuber/characters/kr_별이.yaml))이 이미
들어 있습니다. (자세한 건 [`Open-LLM-VTuber/NOTICE-vendored.md`](Open-LLM-VTuber/NOTICE-vendored.md))

```
[스케줄러] → [시작 공지] → [OBS 시작] → [Open-LLM-VTuber 연결]
      → [채팅 다 반응(핵심 루프)] → [종료 판단] → [마무리] → [OBS 종료]
      → [종료 공지] → [세션 기억 저장] → [다음 방송 대기]   ← 다시 반복
```

---

## 가장 중요한 원칙 (코드에 박혀 있음)

> **"사람처럼"의 판단 주체는 운영자다.** 코드/AI 가 "이러면 사람 같겠지"
> 라고 추측해서 딜레이·채팅 선별 같은 행동 규칙을 미리 박지 않는다.

- **채팅은 기본적으로 다 읽고 다 반응** (`broadcast.respond_to_all_chat=true`)
- **인위적 딜레이를 기본으로 넣지 않음** (`broadcast.artificial_delay_sec=0`)
- **랜덤 변주는 전부 선택지** — 시작/종료 시각, 공지 문구·시간 변주는
  설정으로 켜고 끈다. 기본은 변주 0(정확히).
- 이상한 부분은 **운영자가 보고 지시 → 그때 수정**. (다듬기 워크플로는
  [`docs/OPERATOR.md`](docs/OPERATOR.md))

이 원칙들은 빈말이 아니라 [`aist/chat_pipeline.py`](aist/chat_pipeline.py),
[`aist/config.py`](aist/config.py) 의 기본값과
[`tests/test_config.py`](tests/test_config.py) 의 테스트로 강제됩니다.

---

## 빠른 시작

```bash
# 1) 설치 (핵심 로직은 PyYAML 만으로 동작)
pip install -e .            # 또는: pip install -r requirements.txt
#   기능을 켤 땐: pip install -e ".[all]"  (websockets/obs/discord/...)

# 2) 설정 준비
cp config/config.example.yaml config.yaml
cp config/persona.example.yaml persona.yaml
cp .env.example .env        # 키/토큰은 .env 에 (config.yaml 에 적지 않음)

# 3) 네트워크 없이 점검/미리보기 (지금 바로 됨)
aist check                  # 설정·키 상태 점검
aist plan                   # 다음 방송 일정 + 종료 타임라인
aist persona                # 코어에 들어갈 페르소나 프롬프트
aist announce-preview       # 공지 문구 변주 미리보기

# 4) 방송 코어(이미 저장소에 포함). 프론트엔드(웹 UI)만 받고 설정 적용
bash scripts/setup_openllm_vtuber.sh
#   페르소나를 바꾸면 재주입:
#   aist build-persona --conf Open-LLM-VTuber/conf.yaml --live2d <모델명>

# 5) 배선 점검 후 한 방송만 수동으로(3·4단계) → 완전 자동(5단계)
aist doctor                 # 코어 WS / OBS 가 실제로 닿는지 점검
aist broadcast-now          # 지금 한 방송(시작 수동, 종료는 자동)
aist run                    # 스케줄러로 완전 자동 운영
```

> GPU/OBS/플랫폼 키가 없어도 `check / plan / persona / announce-preview /
> build-persona` 는 동작합니다. 실제 송출(`broadcast-now`, `run`)은 코어·OBS·
> 키가 갖춰진 운영자 환경에서 돌립니다.

---

## 무엇이 들어있나 (부품별)

| 부품 | 파일 | 역할 |
|------|------|------|
| 설정 | `aist/config.py` | 운영자가 만지는 모든 값(YAML) → 타입 있는 설정 |
| 페르소나 | `aist/persona.py` | 3부. 캐릭터 → 코어 `persona_prompt` 생성 |
| 스케줄러 | `aist/scheduler.py` | 5단계. 요일 패턴 + (선택)랜덤 변주 |
| 종료 판단 | `aist/end_judge.py` | 4단계. 최대/최소 시간·정시·(선택)채팅저조·마무리 단계 |
| 채팅 루프 | `aist/chat_pipeline.py` | 다 읽고 다 반응(자연 속도). (선택)폭주 처리 |
| 채팅 수집 | `aist/chat/` | 트위치·유튜브·치지직·SOOP·Kick·트위캐스팅 + **동출(동시)** |
| 코어 브릿지 | `aist/vtuber_bridge.py` | Open-LLM-VTuber `/client-ws` 로 입력 전달 |
| OBS 제어 | `aist/obs_control.py` | obs-websocket 스트림 시작/종료 |
| 공지 | `aist/announce/` | 디스코드(REST)·네이버 카페(공식 API) + 문구 변주 |
| 장기기억 | `aist/memory.py` | "저번에~", 단골 닉네임 |
| 지휘 | `aist/orchestrator.py` | 하루 동선 전체를 묶는 메인 컨트롤러 |
| CLI | `aist/cli.py` | check / plan / persona / build-persona / run ... |

---

## 더 읽기

- [`docs/ROADMAP.md`](docs/ROADMAP.md) — 0~8단계 로드맵과 이 저장소의 범위
- [`docs/INTEGRATION.md`](docs/INTEGRATION.md) — 코어/TTS/OBS/오디오 연결 방법
- [`docs/OPERATOR.md`](docs/OPERATOR.md) — 운영자 준비물·점검·다듬기

## 라이선스 / 주의

- MIT. 단, 외부 오픈소스(Open-LLM-VTuber, GPT-SoVITS 등)는 각자의 라이선스를
  따릅니다.
- 음성 클로닝은 **본인/동의/라이선스 음성만**. 실존 인물 무단 클로닝 금지.
- 플랫폼의 AI 자동·무인 방송 약관, 카페 자동 게시 정책을 진행 전 확인하세요.
