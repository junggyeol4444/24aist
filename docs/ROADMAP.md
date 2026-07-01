# 로드맵 (0~8단계)과 이 저장소의 범위

기획안 7부의 단계별 로드맵에 맞춰, **각 단계에서 이 저장소가 무엇을
제공하는지**를 정리합니다. 한방에 다 하지 말고 한 단계씩 "되는 걸"
확인하며 진행하세요.

| 단계 | 목표 | 이 저장소가 주는 것 | 운영자/외부가 할 일 |
|------|------|--------------------|--------------------|
| **0** 준비/결정 | 플랫폼·콘셉트·페르소나·목소리·서버·키 | `persona.example.yaml`, `aist check` 로 키 점검 | 플랫폼 선택, 키 발급, 목소리 확보 |
| **1** 오픈소스 켜보기 | Open-LLM-VTuber 설치, AI 대화 확인 | `scripts/setup_openllm_vtuber.sh` (다운+개조) | GPU 환경, 코어 단독 실행 확인 |
| **2** 한국어 목소리 | GPT-SoVITS 클로닝 + 페르소나 주입 | `aist build-persona`(conf.yaml 에 주입) | GPT-SoVITS 학습, conf 의 ref_audio |
| **3** 채팅소통+송출 ★ | 사람이 켜면 AI 가 채팅에 반응 | `chat/`(6개 플랫폼+동출), `chat_pipeline.py`, `vtuber_bridge.py`, `obs_control.py`, `aist broadcast-now` | OBS·가상오디오 세팅, 비공개 테스트 |
| **4** 종료 자동화 | 끄는 건 AI 가 알아서 | `end_judge.py`(설정 기반 종료 룰 + 마무리) | 종료 값 조정(설정) |
| **5** 시작 자동화 ★ | 정해진 시간에 스스로 켬 | `scheduler.py`, `orchestrator.run()`, `aist run` | 시작 시각/요일 설정 |
| **6** 공지 자동화 | 디스코드 → 네이버 카페 | `announce/`(discord_bot, naver_cafe, composer) | 디스코드 봇·네이버 앱 등록 |
| **7** 24h 서버화 ★ | 며칠씩 알아서, 자동 재시작 | systemd 유닛 예시(`docs/INTEGRATION.md`), 로그 | 서버 배포, 며칠 운영하며 안정화 |
| **8**(선택) 게임 | 마인크래프트 등 봇 연동 | (확장 자리) 코어/AIRI 연동 검토 | 게임 봇 연동 |

★ = 기획안이 강조한 핵심 검증/달성 지점.

## 단계별 실행 예

```bash
# 0단계: 결정·점검
aist check

# 1단계: 코어 다운 + 개조
bash scripts/setup_openllm_vtuber.sh

# 2단계: 페르소나/TTS 주입 (목소리는 conf.yaml 에서 GPT-SoVITS 설정)
aist build-persona --conf third_party/Open-LLM-VTuber/conf.yaml --live2d <모델명>

# 3단계: 채팅 소통 + 송출 (시작 수동, 종료 자동) — 비공개 테스트
aist broadcast-now

# 4·5단계: 종료/시작 자동화는 설정만 바꾸면 같은 코드가 함
#   end_judge.* 로 종료 룰, scheduler.weekly 로 시작 시각 → 그다음:
aist run

# 6단계: 공지 — config 의 announce.discord / announce.naver_cafe 를 켜고
aist announce-preview          # 문구 먼저 확인
```

## "수동 → 반자동 → 완전자동" 매핑

- **수동**: `aist broadcast-now` 로 사람이 켜고, 종료만 자동(3·4단계).
- **반자동**: 위에 공지 자동화까지(6단계).
- **완전자동**: `aist run` — 스케줄러가 켜고, 종료 판단이 끄고, 공지까지
  스스로(5·7단계).

각 단계는 이전 단계 위에 **설정/명령만 추가**해서 올라갑니다. 코드 구조를
갈아엎지 않습니다.
