# 운영자 가이드 — 준비물 · 점검 · 다듬기

이 프로젝트의 작업 원칙은 **"운영자가 핸들을 쥔다"** 입니다. 무엇이 사람
같고 무엇이 이상한지의 판단 주체는 운영자입니다. 코드/AI 는 단순한 디폴트로
만들어 두고, 운영자가 보고 지시하면 그 방향으로 고칩니다.

## 1. 운영자가 준비/판단하는 것

| 항목 | 어디에 | 비고 |
|------|--------|------|
| GPU 실행 환경 | 집 GPU PC 또는 GPU 클라우드 | 음성·아바타에 GPU 필요 |
| LLM API 키 | `.env` (`OPENAI_API_KEY` 등) | 공지·코어 품질 |
| 디스코드 봇 토큰 | `.env` `DISCORD_BOT_TOKEN` | 봇 생성→토큰→서버 초대 |
| 네이버 앱 키 | `.env` `NAVER_*` | 개발자센터 앱 등록(OAuth2) |
| 트위치 채널/토큰 | `.env` `TWITCH_*` | 토큰 없으면 익명 읽기 |
| OBS WebSocket 비번 | `.env` `OBS_PASSWORD` | OBS 설정에서 발급 |
| 목소리 데이터 | GPT-SoVITS | **본인/동의/라이선스만** |
| Live2D 모델 | 코어 conf | 제작/의뢰/구매 |
| 페르소나 방향 | `persona.yaml` | 캐릭터만, 행동 규칙 X |

키가 제대로 들어갔는지: `aist check`

### 키/토큰 발급 빠른 안내

- **디스코드 봇**: Developer Portal → New Application → Bot → Reset Token 으로
  토큰 발급 → OAuth2 URL 로 서버 초대(권한: Send Messages). 채널 ID 는 디스코드
  개발자 모드 켜고 채널 우클릭 → ID 복사 → `config.yaml` `announce.discord.channel_id`.
- **네이버 카페 공식 API**: 네이버 개발자센터에서 앱 등록 → 카페 API 사용 설정
  → OAuth2 로 `access_token`/`refresh_token` 발급. 본인이 운영하는 카페가 가장
  안전. `cafe_id`/`menu_id` 는 `config.yaml` `announce.naver_cafe` 에.
- **트위치**: `TWITCH_CHANNEL` 만 있으면 익명으로 채팅을 읽을 수 있음. 채팅으로
  말도 하게 하려면 봇 계정 OAuth 토큰(`oauth:` 접두어) 발급.

## 2. 하루 5~10분 점검 (안정화 후)

- **방송 후 리포트 읽기**: `data/reports/` 최신 파일(또는 `aist report`).
  누가 왔는지/단골/슈퍼챗/**AI 발화 전문**이 한 파일에 있다. 사고 발언
  점검은 여기 "AI 발화 전문" 섹션만 훑으면 된다.
- 배선 점검: `aist doctor` (코어 WS / OBS / 플랫폼 채팅 도달까지).
- 로그에서 에러/이상 반복이 없는지 (`journalctl -u aist -f` 또는
  `data/logs/aist.log`). 방송별 상세 기록은 `data/logs/transcripts/`.
- API 비용·토큰 만료 확인(네이버 토큰은 자동 갱신 시도하지만 만료 시 재발급).
- 종료가 의도대로 됐는지(`aist plan` 으로 다음 일정·종료 타임라인 확인).

> "완전 무인"은 환상입니다. 초반 몇 달은 손이 많이 가고(거의 공동 운영),
> 안정화 후에야 저관리가 됩니다. 완전 방치는 위험합니다.

## 3. 다듬기 워크플로 (수시)

방송을 보다가 이상하면, **구체적으로** 지시하세요. 어디를 고칠지 같이 정리:

| 바꾸고 싶은 것 | 보통 어디를 고치나 |
|----------------|--------------------|
| 말투/성격 | `persona.yaml` → `aist build-persona` 로 재주입 |
| 혼잣말이 너무 많음 | `config.yaml` `broadcast.idle_*`(빈도↓) 또는 끄기 |
| 더 빨리/천천히 답 | `broadcast.artificial_delay_sec`(기본 0 유지 권장) |
| 너무 일찍/늦게 끔 | `end_judge.max_minutes/min_minutes` |
| 채팅 없으면 끄고 싶음 | `end_judge.chat_low.enabled: true` |
| 시작 시각 매번 같음이 싫음 | `scheduler.start_jitter_min`(>0) |
| 공지가 단조로움 | `announce.style: varied`(기본) / 고정 원하면 `fixed` |
| 새벽 공지 막기 | `announce.avoid_late_night`, `late_night_window` |

> 핵심: **랜덤 변주·채팅 저조 종료·딜레이는 전부 선택**입니다. 코드가 "봇
> 티 난다"며 강제로 넣지 않습니다. 넣을지는 운영자가 정합니다.

### Claude Code 에게 줄 때 (복붙 템플릿)

```
방송 보니까 이 부분을 바꾸고 싶어:
(여기에 구체적으로 — 예: "이 말투가 어색해, 이렇게 바꿔줘",
 "혼잣말을 좀 줄여", "이 채팅엔 더 길게 반응해줘" 등)

이 방향으로 고쳐줘. 어디(프롬프트/설정/말투 데이터)를 바꾸면 되는지
알려주고 수정해줘.
```

## 4. AI티 제거 — 운영자 지시 반영 내역 (2026-07)

운영자가 "사람이 방송하는 것처럼"을 지시하여 다음이 반영됨. 각각 설정으로
되돌릴 수 있음:

| 반영 내용 | 어디서 조정 |
|---|---|
| **입 하나 모델**: 말 안 하는 중 즉답, 말하는 중이면 쌓았다가 말 끝나면 전부 이어받음 (답변 겹침 버그도 해결) | `broadcast.core_busy_timeout_sec` |
| **눈치 종료**: 예정 시각이 돼도 소강 타이밍 잡아 마무리 (시작 시각은 항상 동일 유지) | `end_judge.wind_down.natural_pause_lull_sec`, `max_overtime_minutes` |
| **눈치 혼잣말**: 정각 타이머 삭제, 연속 혼잣말이면 간격 점점 증가 | `broadcast.idle_backoff_*` |
| **무대 규칙**: 귓속말/프롬프트/시스템 언급 금지, "AI지?" 캐물음엔 RP로 받아치기, 비서 말투 금지 | `aist/persona.py` 무대 규칙(페르소나 재주입: `aist build-persona`) |
| **채팅 태그 자연화**: `[닉/twitch]` → `닉: 내용` (동출일 때만 `닉 (치지직): 내용`) | 코드 기본 |
| **공지 반복 방지**: 조합 변주 + 최근 문구 기억 | `announce.history_size` |
| **OBS**: 아바타 영역만 캡처(자막·귓속말 원문 화면 노출 금지) | `docs/INTEGRATION.md` §3 |

## 5. 리스크 체크리스트

- [ ] 음성: 본인/동의/라이선스 음성만 썼는가
- [ ] 플랫폼: AI 자동·무인 방송 약관을 확인했는가
- [ ] 카페: 공식 API 우선, 셀레늄은 보조·저빈도·본인 카페만
- [ ] 돌발 발언: 페르소나 `taboos` 와 코어 필터로 보강했는가
- [ ] 수익화 시: 플랫폼 수익화/AI 콘텐츠 규정 확인했는가
