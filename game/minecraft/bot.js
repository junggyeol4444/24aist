// =============================================================================
// 마인크래프트 사이드카 — mineflayer 봇 + 이벤트 WebSocket 중계
//
// 역할: 마인크래프트 서버에 봇으로 접속해, 게임 이벤트를 WebSocket(JSON)으로
// 파이썬 레이어(aist)에 중계한다. aist 의 MinecraftFeed 가 이걸 받아
// AI 반응으로 잇는다.
//
// 실행:
//   cd game/minecraft && npm install && node bot.js
// 환경변수:
//   MC_HOST(기본 127.0.0.1) MC_PORT(25565) MC_USERNAME(aist_bot)
//   MC_AUTH(offline | microsoft)  WS_PORT(8765)
//
// 보내는 이벤트(JSON 한 줄):
//   {"event":"spawn"} {"event":"death"} {"event":"respawn"}
//   {"event":"kicked","reason":"..."} {"event":"health_low","health":4}
//   {"event":"chat","username":"Steve","message":"hi"}
// 받는 명령:
//   {"cmd":"say","text":"..."}   → 게임 채팅으로 말하기
// =============================================================================
const mineflayer = require('mineflayer')
const { WebSocketServer } = require('ws')

const MC_HOST = process.env.MC_HOST || '127.0.0.1'
const MC_PORT = parseInt(process.env.MC_PORT || '25565', 10)
const MC_USERNAME = process.env.MC_USERNAME || 'aist_bot'
const MC_AUTH = process.env.MC_AUTH || 'offline'
const WS_PORT = parseInt(process.env.WS_PORT || '8765', 10)
const HEALTH_LOW_THRESHOLD = 6  // 하트 3개

// --- WebSocket 서버 (aist 가 붙는 곳) ---------------------------------------
const wss = new WebSocketServer({ port: WS_PORT })
const clients = new Set()

function broadcast(obj) {
  const line = JSON.stringify(obj)
  for (const ws of clients) {
    if (ws.readyState === 1) ws.send(line)
  }
}

console.log(`[sidecar] WebSocket 대기: ws://127.0.0.1:${WS_PORT}`)

// --- mineflayer 봇 (죽으면 재접속) ------------------------------------------
let bot = null
let healthLowSent = false

function createBot() {
  console.log(`[sidecar] 마인크래프트 접속 시도: ${MC_HOST}:${MC_PORT} (${MC_USERNAME})`)
  bot = mineflayer.createBot({
    host: MC_HOST,
    port: MC_PORT,
    username: MC_USERNAME,
    auth: MC_AUTH,
  })

  bot.once('spawn', () => {
    healthLowSent = false
    broadcast({ event: 'spawn' })
    console.log('[sidecar] spawn')
  })

  bot.on('death', () => {
    broadcast({ event: 'death' })
    console.log('[sidecar] death')
  })

  bot.on('respawn', () => {
    broadcast({ event: 'respawn' })
  })

  bot.on('health', () => {
    if (bot.health <= HEALTH_LOW_THRESHOLD && !healthLowSent) {
      healthLowSent = true
      broadcast({ event: 'health_low', health: bot.health })
    } else if (bot.health > HEALTH_LOW_THRESHOLD) {
      healthLowSent = false
    }
  })

  bot.on('chat', (username, message) => {
    if (username === bot.username) return
    broadcast({ event: 'chat', username, message })
  })

  bot.on('kicked', (reason) => {
    broadcast({ event: 'kicked', reason: String(reason) })
    console.log('[sidecar] kicked:', reason)
  })

  bot.on('error', (err) => {
    console.log('[sidecar] bot error:', err.message)
  })

  bot.on('end', () => {
    console.log('[sidecar] 연결 종료 → 10초 후 재접속')
    setTimeout(createBot, 10000)
  })
}

createBot()

// --- aist 로부터의 명령 -------------------------------------------------------
wss.on('connection', (ws) => {
  clients.add(ws)
  console.log('[sidecar] aist 연결됨')
  ws.on('message', (raw) => {
    let msg
    try { msg = JSON.parse(raw.toString()) } catch { return }
    if (msg.cmd === 'say' && msg.text && bot) {
      try { bot.chat(String(msg.text).slice(0, 250)) } catch {}
    }
  })
  ws.on('close', () => clients.delete(ws))
})
