# 마인크래프트 사이드카 (8단계, 선택)

mineflayer 봇이 마인크래프트 서버에 접속해 게임 이벤트를 WebSocket 으로
중계하고, aist 의 `MinecraftFeed` 가 그걸 AI 반응으로 잇습니다.
게임 중에도 시청자 채팅 소통은 그대로 유지됩니다.

## 실행

```bash
# 1) 의존성 설치 (Node.js 18+ 필요)
cd game/minecraft && npm install

# 2) 봇 실행 (환경변수로 서버 지정)
MC_HOST=127.0.0.1 MC_PORT=25565 MC_USERNAME=aist_bot node bot.js
#   정품 서버면 MC_AUTH=microsoft (콘솔의 로그인 안내를 따름)

# 3) aist 쪽에서 게임 켜기 — config.yaml:
#   game:
#     enabled: true
#     ws_url: "ws://127.0.0.1:8765"
```

## 무엇이 일어나나

| 게임 이벤트 | AI 반응 |
|---|---|
| 죽음(death) | "(게임 상황: 방금 게임에서 죽었어.)" 큐 → 페르소나가 캐릭터답게 반응 |
| 체력 위험(health_low) | 위험 상황 큐 |
| 튕김(kicked)/리스폰 | 상황 큐 |
| 게임 내 채팅 | `[닉/minecraft]` 로 시청자 채팅처럼 전달 (끄려면 `forward_game_chat: false`) |

어떤 이벤트에 반응할지는 `game.react_events` 로 조정합니다.
"이렇게 말해라"는 강제하지 않고 상황만 알립니다 — 말은 페르소나가 정합니다.

## 24시간 운영

봇이 죽거나 튕기면 10초 후 자동 재접속하고, aist 쪽 연결이 끊겨도 5초
간격으로 재연결합니다. systemd 로 사이드카도 자동 재시작하려면
`deploy/` 의 예시를 참고하세요.
