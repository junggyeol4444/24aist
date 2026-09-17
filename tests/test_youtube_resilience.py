"""유튜브 채팅이 방송 내내 버티는지.

다른 플랫폼(치지직·트위치·숲·킥)에는 이미 들어가 있던 보호가 유튜브에만
빠져 있었다. 진짜 코드를 돌려서 확인한 것:
  - 자동발견 중 DNS 오류 한 번에 messages() 가 통째로 끝났다
    (순간적인 네트워크 끊김 한 번 = 그 방송 유튜브 채팅 사망)
  - 라이브를 기다리는 동안 30초마다 같은 줄을 찍었다(측정: 74줄)
  - pytchat 미설치가 RuntimeError 로 올라가 오케스트레이터가 소스를
    계속 새로 만들었다(fatal 로 알려야 멈춘다)
"""

import asyncio
import builtins
import logging
import sys

import pytest

from aist.chat import youtube as Y


async def _drain(src, seconds=0.6):
    """messages() 를 잠깐 돌리고, 밖으로 새어 나온 예외를 돌려준다."""
    out = []

    async def run():
        async for m in src.messages():
            out.append(m)

    t = asyncio.create_task(run())
    await asyncio.sleep(seconds)
    t.cancel()
    try:
        await t
    except asyncio.CancelledError:
        return out, None
    except Exception as e:  # noqa: BLE001
        return out, e
    return out, None


def test_자동발견_중_네트워크_오류로_채팅이_끝나지_않는다(monkeypatch):
    def boom(channel):
        raise ConnectionError("Temporary failure in name resolution")

    monkeypatch.setattr(Y, "resolve_live_video_id", boom)
    src = Y.YouTubeChat(channel="@별이")
    _, err = asyncio.run(_drain(src))
    assert err is None, f"예외가 밖으로 샜다: {err!r}"


def test_라이브를_기다리는_동안_같은_줄을_도배하지_않는다(monkeypatch, caplog):
    monkeypatch.setattr(Y, "resolve_live_video_id", lambda channel: None)
    real_sleep = asyncio.sleep

    async def fast(s):
        await real_sleep(0.001 if s >= 5 else s)

    monkeypatch.setattr(Y.asyncio, "sleep", fast)
    src = Y.YouTubeChat(channel="@별이")
    with caplog.at_level(logging.INFO, logger="aist.chat.youtube"):
        asyncio.run(_drain(src, 0.5))
    waits = [r for r in caplog.records if "아직 라이브가 아님" in r.getMessage()]
    # 몇 번 확인했든 로그는 그 1/20 이하여야 한다(1·10번째, 그 뒤 60번마다).
    # 예전에는 확인할 때마다 한 줄씩이라 실제 방송에서 시간당 120줄이었다.
    assert src._waits > 50, "이 테스트가 의미 있으려면 여러 번 돌아야 한다"
    assert 0 < len(waits) <= src._waits / 20, (
        f"{src._waits}번 확인에 로그 {len(waits)}줄")


def test_pytchat_미설치는_예외가_아니라_fatal_로_알린다(monkeypatch):
    real_import = builtins.__import__

    def blocked(name, *a, **k):
        if name.split(".")[0] == "pytchat":
            raise ImportError("No module named 'pytchat'")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", blocked)
    for m in [x for x in sys.modules if x.startswith("pytchat")]:
        monkeypatch.delitem(sys.modules, m)

    src = Y.YouTubeChat(video_id="abcdefghijk")
    _, err = asyncio.run(_drain(src, 0.1))
    assert err is None
    assert "pytchat" in src.fatal


class _Author:
    def __init__(self, name):
        self.name = name


class _Item:
    """글 없이 돈만 보낸 슈퍼챗 — message 속성이 아예 없다."""
    def __init__(self):
        self.type = "superChat"
        self.amountString = "\u20a910,000"
        self.author = _Author("큰손")


class _Data:
    def sync_items(self):
        return [_Item()]


class _Chat:
    def __init__(self):
        self._n = 0

    def is_alive(self):
        self._n += 1
        return self._n <= 1

    def get(self):
        return _Data()

    def terminate(self):
        pass


def test_글_없는_후원도_버리지_않는다(monkeypatch):
    """유튜브 슈퍼챗은 글 없이 돈만 보낼 수 있다.

    버리면 시청자는 돈을 냈는데 방송인은 모르고 지나간다.
    """
    import types
    stub = types.ModuleType("pytchat")
    stub.create = lambda video_id: _Chat()
    monkeypatch.setitem(sys.modules, "pytchat", stub)

    src = Y.YouTubeChat(video_id="abcdefghijk")
    got, err = asyncio.run(_drain(src, 0.3))
    assert err is None
    assert got, "후원이 통째로 사라졌다"
    assert got[0].is_superchat is True
    assert got[0].amount == "\u20a910,000"
    assert got[0].author == "큰손"
    assert got[0].text == ""
