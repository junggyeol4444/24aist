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

> 이건 **"사람처럼 방송하는 AI"** 다. LLM 이 채팅에 답을 뱉는 물건이 아니다.
> **사람같음은 옵션이 아니라 기본값이고**, 무엇이 자연스러운지의 최종 판단은
> 운영자가 한다(운영자가 보고 지시 → 수정).

**기본으로 켜져 있는 것 (끄는 게 아니라 다듬는 대상):**
- **입 하나 모델** — 말 안 하는 중이면 즉답, 말하는 중이면 채팅이 쌓임.
  말이 끝나면 쌓인 걸 **하나하나 다 답하는 게 아니라, 사람이 채팅창
  훑어보듯** 자연스럽게 반응(구조 자체라 끌 수 없음)
- **채팅은 다 읽고 다 반응** — 선별·인위적 딜레이 없음
- **여는 인사 오프닝** — 방송 켜지면 방송인처럼 "안녕~ 오늘도 왔어요"로 시작
- **눈치껏 종료** — 종료 시각이 와도 말 중간·밀린 채팅·방금 온 후원 중엔
  안 끊고, 지금 하던 걸 끝낸 자연스러운 틈에 마무리(채팅이 조용해지길
  기다리는 게 아님 — 인기 방송은 채팅이 안 끊긴다). 예고(20분 전) →
  틈에서 마무리 인사 → 여운 후 종료
- **진행자 혼잣말** — 방송인은 진행자다. 채팅이 없을수록 조용해지는 게
  아니라, 짧은 공백만 생겨도 말을 걸어 방송을 끌고 감
- **무대 규칙** — 귓속말/시스템 언급 금지, "AI지?"엔 캐릭터로 받아침
- **공지: 시작 30분 전 예고 + 매번 다른 문구 + 반복 회피 + 새벽 회피**
- **시작 시각은 항상 동일** (운영자 지시 — 사람도 정해진 시간에 켠다)

설정(config.yaml)은 이 동작들을 **끄기 위한 게 아니라 값을 다듬기 위한**
것입니다. 다듬기 워크플로는 [`docs/OPERATOR.md`](docs/OPERATOR.md).

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
| 장기기억 | `aist/memory.py` | "저번에~", 단골 닉네임 (+chroma 의미검색) |
| 트랜스크립트 | `aist/transcript.py` | 채팅+**AI 발화 전문** 기록(사고발언 점검) |
| 방송후 리포트 | `aist/report.py` | 다시보기 학습 — 매 방송 자동 생성(`aist report`) |
| 컨텐츠 제작 | `aist/content.py` | 하이라이트 후보(채팅 급증 구간)·제목 초안(`aist content`) |
| 게임(8단계) | `aist/game/` + `game/minecraft/` | 마인크래프트(mineflayer 사이드카) |
| 지휘 | `aist/orchestrator.py` | 하루 동선 전체를 묶는 메인 컨트롤러 |
| CLI | `aist/cli.py` | check / plan / doctor / report / build-persona / run ... |
| 배포(7단계) | `deploy/` | systemd 유닛 + install.sh (자동 재시작) |

---

## 더 읽기

- [`docs/ROADMAP.md`](docs/ROADMAP.md) — 0~8단계 로드맵과 이 저장소의 범위
- [`docs/INTEGRATION.md`](docs/INTEGRATION.md) — 코어/TTS/OBS/오디오 연결 방법
- [`docs/OPERATOR.md`](docs/OPERATOR.md) — 운영자 준비물·점검·다듬기

## 검증 상태 (솔직하게)

"완성"을 과장하지 않기 위해 정리합니다.

**검증됨(자동 테스트/실제 라이브러리로 확인, 44개 테스트):**
- 스케줄러·종료판단·페르소나·공지 변주·설정·장기기억 로직
- 오케스트레이터 한 사이클 통합(채팅이 소스→파이프라인→브릿지로 실제로
  흐르고, 순서대로 다 반응하는지)
- 브릿지가 **실제 websockets 서버**와 text-input/ai-speak-signal 송수신 +
  수신 드레인(장시간 메모리 누수 방지)
- 코어 통신 규약을 vendored Open-LLM-VTuber 소스로 대조

**검증됨(추가): 57개 테스트**
- 방송 트랜스크립트(채팅+AI 발화)와 방송 후 리포트가 방송 사이클에서
  실제로 생성되는 것까지 통합 테스트로 확인.
- 게임 이벤트→AI 반응/게임 채팅 전달, 유튜브 라이브 ID 파싱.

**아직 실제 서비스로 못 돌려본 것(이 환경엔 GPU/실계정 없음 → 운영자 테스트 필요):**
- Open-LLM-VTuber 코어 실행 + TTS/Live2D 실제 송출
- 각 플랫폼 **실계정 채팅 연결**. 프로토콜/접속상수는 레퍼런스로 확인했으나
  라이브 확인은 필요. 특히 **SOOP** 는 패킷 필드 인덱스 보정이 필요할 수 있음
  (`aist/chat/soop.py` 주석 표시). 치지직 REST 는 버전 변동 가능.
  → `aist doctor` 가 활성 플랫폼의 도달성(온에어 여부)까지 점검합니다.
- 디스코드/네이버 카페 실제 게시(토큰 필요). 네이버 **셀레늄 보조**는 실제
  구현했으나 카페 글쓰기 DOM 이 자주 바뀌어 셀렉터 조정이 필요할 수 있음
  (`_selenium_post` STEP 로그로 확인).
- **영상 동출(다중 RTMP)**: obs-multi-rtmp 플러그인 제어 코드는 구현됨
  (`obs.simulcast`). 플러그인 설치 + 요청명 확인은 운영자 환경에서.
- **chroma 기억 백엔드**: 구현됨(`memory.backend: chroma`). 임베딩 모델
  다운로드는 첫 실행 시 필요. 미설치면 recall 은 키워드 검색으로 동작.

→ 즉, **로직·배선은 검증됨. 외부 실연동은 운영자가 키/환경 넣고 `aist doctor`
   → `aist broadcast-now` 로 확인하며 다듬는 단계**가 남아 있습니다(기획안 3단계).

## 라이선스 / 주의

- MIT. 단, 외부 오픈소스(Open-LLM-VTuber, GPT-SoVITS 등)는 각자의 라이선스를
  따릅니다.
- 음성 클로닝은 **본인/동의/라이선스 음성만**. 실존 인물 무단 클로닝 금지.
- 플랫폼의 AI 자동·무인 방송 약관, 카페 자동 게시 정책을 진행 전 확인하세요.
