import asyncio

from aist.chat.base import ChatMessage, ChatSource
from aist.config import BroadcastConfig, FloodHandling
from aist.chat_pipeline import ChatPipeline


class FakeBridge:
    def __init__(self):
        self.said = []
        self.proactive = 0

    async def say_to_ai(self, text, source=None, platform=None, **kw):
        self.said.append((source, text))

    async def proactive_speak(self):
        self.proactive += 1


class FakeSource(ChatSource):
    platform = "fake"

    def __init__(self, messages):
        self._messages = messages

    async def messages(self):
        for m in self._messages:
            yield m
            await asyncio.sleep(0)
        # 끝나지 않게 잠깐 대기(소비 완료 후 stop 설정될 시간)
        await asyncio.sleep(5)

    async def close(self):
        pass


def _msgs(n, sc=False):
    return [ChatMessage(author=f"u{i}", text=f"m{i}", platform="fake",
                        is_superchat=sc) for i in range(n)]


def _all_texts(said):
    return "\n".join(t for (_s, t) in said)


def test_all_chat_reaches_ai():
    """다 반응(절대 원칙): 채팅 5개가 전부 AI 에게 전달된다.

    '입 하나' 모델이라 첫 개는 즉시, 나머지는 말 끝난 뒤 묶여 전달될 수
    있지만 하나도 버려지지 않는다.
    """
    async def run():
        bridge = FakeBridge()
        reads = []
        cfg = BroadcastConfig(idle_proactive_speak=False, core_busy_timeout_sec=0.001)
        pipe = ChatPipeline(bridge, cfg, on_message=lambda m: reads.append(m.author))
        stop = asyncio.Event()
        task = asyncio.create_task(pipe.run(FakeSource(_msgs(5)), stop))
        await asyncio.sleep(0.9)   # pacer(0.3s)가 잔여분 흘려보낼 시간
        stop.set()
        await asyncio.wait_for(task, timeout=2)
        return bridge.said, reads

    said, reads = asyncio.run(run())
    joined = _all_texts(said)
    for i in range(5):
        assert f"m{i}" in joined          # 다 반응 (절대 원칙)
    assert len(reads) == 5                # 다 읽음


def test_one_mouth_buffers_while_speaking_and_resumes():
    """말하는 중엔 쌓고, 말 끝(chain-end)나는 순간 전부 이어받는다."""
    async def run():
        bridge = FakeBridge()
        cfg = BroadcastConfig(idle_proactive_speak=False)   # timeout 기본(90s)
        pipe = ChatPipeline(bridge, cfg)
        stop = asyncio.Event()
        task = asyncio.create_task(pipe.run(FakeSource(_msgs(3)), stop))
        await asyncio.sleep(0.5)
        # m0 은 즉시 나가고 busy 잠김 → m1, m2 는 쌓여 있어야 함
        first_said = list(bridge.said)
        pending_before = pipe.has_pending()
        # 코어가 말 끝 신호를 보냄 → pacer 가 쌓인 걸 한 호흡으로 전달
        pipe.on_core_message({"type": "control", "text": "conversation-chain-end"})
        await asyncio.sleep(0.7)
        stop.set()
        await asyncio.wait_for(task, timeout=2)
        return first_said, pending_before, bridge.said

    first_said, pending_before, said = asyncio.run(run())
    assert len(first_said) == 1 and "m0" in first_said[0][1]
    assert pending_before is True
    # 말 끝난 뒤 m1+m2 가 '한 번에' 이어받아짐 (버려진 것 없음, 순서 유지)
    assert len(said) == 2
    batch = said[1][1]
    assert "m1" in batch and "m2" in batch
    assert batch.index("m1") < batch.index("m2")
    # 쌓인 채팅은 '훑어보듯' 반응하라는 귓속말이 함께 감(하나하나 다 답 X)
    assert "훑어보듯" in batch


def test_flood_handling_limits_forward_but_reads_all():
    async def run():
        bridge = FakeBridge()
        reads = []
        cfg = BroadcastConfig(
            idle_proactive_speak=False, core_busy_timeout_sec=0.001,
            flood_handling=FloodHandling(enabled=True, max_per_window=1, window_sec=10),
        )
        pipe = ChatPipeline(bridge, cfg, on_message=lambda m: reads.append(m.author))
        stop = asyncio.Event()
        task = asyncio.create_task(pipe.run(FakeSource(_msgs(4)), stop))
        await asyncio.sleep(0.6)
        stop.set()
        await asyncio.wait_for(task, timeout=2)
        return bridge.said, reads

    said, reads = asyncio.run(run())
    assert len(reads) == 4         # 읽기는 전부
    assert len(said) == 1          # 폭주 구간이라 AI 발화로는 1건만


def test_idle_gap_is_bounded_and_reset():
    """진행자 혼잣말: 다음 말 걸 공백이 min~max 안에 있고, 채팅/발화로 리셋."""
    import time
    cfg = BroadcastConfig(idle_gap_min_sec=6, idle_gap_max_sec=15)
    pipe = ChatPipeline(FakeBridge(), cfg)
    gap = pipe._next_idle_at - time.monotonic()
    assert 6 <= gap <= 15 + 0.05
    # 말하면(_mark_busy) 공백이 다시 잡힌다
    pipe._next_idle_at = 0.0
    pipe._mark_busy()
    assert pipe._next_idle_at > time.monotonic()


def test_idle_speak_fires_when_quiet():
    """짧은 공백만 생겨도 진행자처럼 말을 잇는다(채팅 없어도 방송 끌기)."""
    async def run():
        bridge = FakeBridge()
        # 즉시 말 걸도록 gap 을 0 근처로
        cfg = BroadcastConfig(idle_gap_min_sec=2, idle_gap_max_sec=2)
        pipe = ChatPipeline(bridge, cfg)
        pipe._next_idle_at = 0.0          # 지금 바로 말할 때가 됨
        await pipe._maybe_idle_speak()
        return bridge.proactive

    assert asyncio.run(run()) == 1


# =========================================================================
# 폭주 시 한 메시지가 수십만 자가 되던 것.
#
# 말하는 동안 쌓인 채팅을 한 번에 넘기는데 상한이 없었다. 5000건이면
# 13만 4천 자짜리 메시지 하나가 코어로 갔고, LLM 이 조용히 잘라먹어
# 채팅이 사라지는데 아무도 몰랐다 — 기획안 1-2 "다 읽고 다 반응" 이
# 소리 없이 깨진다.
#
# 버리는 게 아니다: 기록·기억에는 전부 남고, AI 에게는 최근 것 +
# "그 외 N건" 으로 규모를 알린다(사람 방송인도 쏟아지면 다 못 읽고
# "엄청 빠르네" 하고 반응한다 — 기획안 1-2 의 그 상황).
# =========================================================================
def _big_batch(n):
    from aist.chat.base import ChatMessage
    return [ChatMessage(author=f"시청자{i}", text="오늘 방송 진짜 재밌어요 ㅋㅋㅋ",
                        platform="twitch") for i in range(n)]


def _send_and_get(batch, **cfg_over):
    from aist.config import BroadcastConfig, SafetyConfig
    bridge = FakeBridge()
    pipe = ChatPipeline(bridge, BroadcastConfig(**cfg_over), safety=SafetyConfig())
    asyncio.run(pipe._send_batch(batch))
    return bridge.said[0][1]


def test_small_batch_is_untouched():
    text = _send_and_get(_big_batch(10))
    assert "그 외" not in text
    assert text.count("\n") == 10        # 귓속말 1줄 + 채팅 10줄


def test_huge_batch_is_capped():
    text = _send_and_get(_big_batch(5000))
    assert len(text) < 10000, f"여전히 {len(text)}자"


def test_huge_batch_tells_ai_how_many_more():
    text = _send_and_get(_big_batch(5000))
    assert "그 외" in text and "건 더" in text


def test_cap_keeps_the_most_recent():
    """사람이 채팅창을 보면 최근 것이 눈에 들어온다."""
    text = _send_and_get(_big_batch(1000))
    assert "시청자999" in text, "최근 채팅이 빠졌다"
    assert "시청자0:" not in text


def test_operator_can_raise_the_cap():
    text = _send_and_get(_big_batch(200), max_batch_lines=200, max_batch_chars=100000)
    assert "그 외" not in text


def test_cap_warns_so_operator_notices(caplog):
    _send_and_get(_big_batch(500))
    assert any("쏟아져" in r.getMessage() for r in caplog.records)


# ------------- 웹UI 미접속 = 시청자에게 소리가 안 나가는 상태 -------------
def test_core_mute_reported_after_consecutive_timeouts():
    """말 끝 신호가 연속으로 안 오면 '벙어리 방송'으로 보고 알려야 한다.

    코어는 웹UI 가 '재생 끝났다'고 답해야 대화를 닫는다. 웹UI(OBS 브라우저
    소스)가 안 붙어 있으면 코어는 붙어 있는데 시청자에게는 아무 소리도
    안 나간다. 실제로 브라우저 없이 돌려보니 조용한 화면만 계속 나갔다.
    """
    from aist.chat_pipeline import ChatPipeline
    from aist.config import BroadcastConfig

    cfg = BroadcastConfig(core_busy_timeout_sec=0.001, core_mute_max_strikes=3)
    fired = []
    p = ChatPipeline(object(), cfg, on_core_mute=lambda: fired.append(1))

    def stuck():
        """말 끝 신호가 안 온 채로 폴백 시간이 지난 상태를 만든다."""
        p._mark_busy()
        p._busy_since -= 10
        return p._busy_now()

    for _ in range(3):
        assert stuck() is False           # 매번 타임아웃 처리
    assert fired == [1]
    stuck()                               # 한 번만 알린다(로그 폭발 방지)
    assert fired == [1]


def test_core_mute_streak_resets_on_healthy_end():
    """한 번이라도 정상적으로 말이 끝나면 연속 실패는 끊긴 것으로 본다."""
    from aist.chat_pipeline import ChatPipeline
    from aist.config import BroadcastConfig

    cfg = BroadcastConfig(core_busy_timeout_sec=0.001, core_mute_max_strikes=3)
    fired = []
    p = ChatPipeline(object(), cfg, on_core_mute=lambda: fired.append(1))

    def stuck():
        p._mark_busy()
        p._busy_since -= 10
        p._busy_now()

    for _ in range(2):
        stuck()
    p.on_core_message({"type": "control", "text": "conversation-chain-end"})
    for _ in range(2):
        stuck()
    assert fired == []                    # 2회씩 끊겨 있으므로 아직 아니다


# --------- 코어가 LLM 오류 문구를 그대로 읽는 사고 ----------
def _audio(text):
    return {"type": "audio", "display_text": {"text": text}}


_CORE_LLM_ERROR = ("Error calling the chat endpoint: Rate limit exceeded. "
                   "Please try again later. See the logs for details.")


def _chain(p, *texts):
    """대화 한 덩어리를 흉내낸다(시작 → 발화들 → 끝)."""
    p.on_core_message({"type": "control", "text": "conversation-chain-start"})
    for t in texts:
        p.on_core_message(_audio(t))
    p.on_core_message({"type": "control", "text": "conversation-chain-end"})


# 실제 코어가 429 를 만났을 때 내보낸 세 문장 그대로.
_ERROR_CHAIN = ("Error calling the chat endpoint: Rate limit exceeded.",
                "Please try again later.",
                "See the logs for details.")


def test_core_llm_error_speech_detected_and_reported():
    """방송인이 영어 오류 문구를 계속 읽으면 방송을 내려야 한다."""
    from aist.chat_pipeline import ChatPipeline
    from aist.config import BroadcastConfig

    seen = []
    p = ChatPipeline(object(), BroadcastConfig(core_error_max_strikes=3),
                     on_core_brain_dead=lambda t: seen.append(t))
    for _ in range(2):
        _chain(p, *_ERROR_CHAIN)
    assert seen == []
    _chain(p, *_ERROR_CHAIN)
    assert len(seen) == 1 and "Rate limit" in seen[0]
    _chain(p, *_ERROR_CHAIN)
    assert len(seen) == 1          # 한 번만 알린다


def test_error_followup_sentences_do_not_reset_streak():
    """오류 문구 뒤에 따라오는 문장이 연속 카운터를 리셋하면 안 된다.

    접두사는 첫 문장에만 있다. 줄 단위로 세면 "Please try again later." 가
    정상 발화로 보여 카운터가 영원히 1 에 머문다(실제 방송에서 그랬다).
    """
    from aist.chat_pipeline import ChatPipeline
    from aist.config import BroadcastConfig

    seen = []
    p = ChatPipeline(object(), BroadcastConfig(core_error_max_strikes=2),
                     on_core_brain_dead=lambda t: seen.append(t))
    _chain(p, *_ERROR_CHAIN)
    _chain(p, *_ERROR_CHAIN)
    assert len(seen) == 1


def test_core_llm_error_streak_resets_on_normal_speech():
    """정상 대화가 한 번이라도 끝나면 연속 오류는 끊긴 것이다."""
    from aist.chat_pipeline import ChatPipeline
    from aist.config import BroadcastConfig

    seen = []
    p = ChatPipeline(object(), BroadcastConfig(core_error_max_strikes=3),
                     on_core_brain_dead=lambda t: seen.append(t))
    _chain(p, *_ERROR_CHAIN)
    _chain(p, *_ERROR_CHAIN)
    _chain(p, "응 그거 나도 봤어")
    _chain(p, *_ERROR_CHAIN)
    _chain(p, *_ERROR_CHAIN)
    assert seen == []


def test_normal_korean_speech_is_not_mistaken_for_error():
    """평범한 발화를 오류로 잘못 보면 멀쩡한 방송이 내려간다."""
    from aist.chat_pipeline import ChatPipeline
    from aist.config import BroadcastConfig

    seen = []
    p = ChatPipeline(object(), BroadcastConfig(core_error_max_strikes=1),
                     on_core_brain_dead=lambda t: seen.append(t))
    for t in ("에러 났대요 ㅋㅋ", "error 라는 게임 알아?", "그 채팅 봤어"):
        _chain(p, t)
    assert seen == []


# --------- TTS 가 죽으면 자막만 나가고 목소리가 없다 ----------
def test_silent_audio_detected():
    """소리 없는 발화가 연속으로 나가면 TTS 가 죽은 것으로 보고 알려야 한다.

    실제 코어에서 확인: TTS 합성이 실패해도 코어는 발화를 멈추지 않고
    audio 필드만 빈 채로(0바이트) 자막을 내보낸다.
    """
    from aist.chat_pipeline import ChatPipeline
    from aist.config import BroadcastConfig

    fired = []
    p = ChatPipeline(object(), BroadcastConfig(tts_silent_max_strikes=3),
                     on_tts_silent=lambda: fired.append(1))
    for _ in range(2):
        p.on_core_message(_audio("안녕하세요"))
    assert fired == []
    p.on_core_message(_audio("반가워요"))
    assert fired == [1]
    p.on_core_message(_audio("또 왔네"))
    assert fired == [1]          # 한 번만 알린다


def test_silent_streak_resets_when_voice_comes_back():
    from aist.chat_pipeline import ChatPipeline
    from aist.config import BroadcastConfig

    fired = []
    p = ChatPipeline(object(), BroadcastConfig(tts_silent_max_strikes=3),
                     on_tts_silent=lambda: fired.append(1))
    p.on_core_message(_audio("하나"))
    p.on_core_message(_audio("둘"))
    ok = _audio("셋"); ok["audio"] = "UklGRi4AAABXQVZF"   # 소리 있음
    p.on_core_message(ok)
    p.on_core_message(_audio("넷"))
    p.on_core_message(_audio("다섯"))
    assert fired == []


def test_display_only_message_without_text_is_not_counted():
    """자막도 없는 메시지는 발화로 치지 않는다(오탐 방지)."""
    from aist.chat_pipeline import ChatPipeline
    from aist.config import BroadcastConfig

    fired = []
    p = ChatPipeline(object(), BroadcastConfig(tts_silent_max_strikes=2),
                     on_tts_silent=lambda: fired.append(1))
    for _ in range(5):
        p.on_core_message({"type": "audio", "display_text": {"text": ""}})
    assert fired == []


# --------- 폭주 처리: 조용히 버리지 않는다, 그렇다고 도배하지도 않는다 -----
def test_flood_drop_is_reported_but_not_every_time(caplog):
    """운영자가 직접 켠 기능이라도, 얼마나 걸러지는지는 보여줘야 한다.

    안 보여주면 기준값이 너무 낮아도 알 수가 없다 — 기획안 1-2 의
    "다 읽고 다 반응" 을 일부러 잠시 끄는 구간이기 때문이다.
    그렇다고 매 건 찍으면 폭주 3시간에 로그가 수천 줄이 된다.
    """
    import logging

    from aist.chat_pipeline import ChatPipeline
    from aist.config import BroadcastConfig, FloodHandling

    cfg = BroadcastConfig(flood_handling=FloodHandling(
        enabled=True, max_per_window=2, window_sec=60))
    p = ChatPipeline(object(), cfg)
    with caplog.at_level(logging.WARNING, logger="aist.chat_pipeline"):
        passed = sum(1 for _ in range(200) if p._should_forward())
    assert passed == 2                      # 상한만큼만 통과
    assert p._flood_dropped == 198
    # 1·10·100회째만 — 198줄이 아니라 세 줄
    assert len(caplog.records) == 3


def test_batch_cap_warning_is_not_repeated_every_batch(caplog):
    """폭주는 몇 초마다 계속 걸린다 — 매번 찍으면 로그가 밀린다."""
    import logging

    from aist.chat_pipeline import ChatPipeline
    from aist.config import BroadcastConfig

    p = ChatPipeline(object(), BroadcastConfig(max_batch_lines=1))
    with caplog.at_level(logging.WARNING, logger="aist.chat_pipeline"):
        for _ in range(50):
            kept, dropped = p._cap_batch(["가", "나", "다"])
            assert len(kept) == 1 and dropped == 2
    assert len(caplog.records) == 2         # 1·10회째만


def test_flood_handling_off_by_default_passes_everything():
    from aist.chat_pipeline import ChatPipeline
    from aist.config import BroadcastConfig

    p = ChatPipeline(object(), BroadcastConfig())
    assert all(p._should_forward() for _ in range(500))
    assert p._flood_dropped == 0
