"""리허설 채팅 — 플랫폼·키 없이 방송 루프를 돌려볼 수 있어야 한다."""

import asyncio

import pytest

from aist.chat.base import ChatMessage
from aist.chat.factory import make_single_source
from aist.chat.rehearsal import RehearsalChat
from aist.config import load_config


def _take(source, n, timeout=5.0):
    async def go():
        out = []
        agen = source.messages()
        async for m in agen:
            out.append(m)
            if len(out) >= n:
                break
        await agen.aclose()
        return out
    return asyncio.run(asyncio.wait_for(go(), timeout))


def test_yields_chat_messages():
    msgs = _take(RehearsalChat(interval_sec=0.01), 5)
    assert len(msgs) == 5
    assert all(isinstance(m, ChatMessage) for m in msgs)
    assert all(m.platform == "rehearsal" for m in msgs)
    assert all(m.author and m.text for m in msgs)


def test_superchat_appears():
    """후원 반응 경로도 리허설에서 밟히도록 가끔 슈퍼챗을 섞는다."""
    msgs = _take(RehearsalChat(interval_sec=0.01, superchat_every=3), 9)
    sc = [m for m in msgs if m.is_superchat]
    assert sc, "슈퍼챗이 하나도 안 나왔다"
    assert all(m.amount for m in sc)


def test_superchat_can_be_disabled():
    msgs = _take(RehearsalChat(interval_sec=0.01, superchat_every=0), 6)
    assert not any(m.is_superchat for m in msgs)


def test_factory_makes_rehearsal_source():
    cfg = load_config("config/config.example.yaml")
    assert isinstance(make_single_source("rehearsal", cfg), RehearsalChat)


def test_rehearsal_needs_no_extra_package():
    """리허설은 추가 패키지 없이 돌아야 한다(그게 요점)."""
    from aist import preflight
    cfg = load_config("config/config.example.yaml")
    cfg.platform = "rehearsal"
    cfg.platforms = []
    chat_needs = [n for n in preflight.needs(cfg) if "채팅" in n.feature]
    assert chat_needs == []


def test_probe_describes_itself():
    assert "리허설" in asyncio.run(RehearsalChat().probe())
