"""공지 자동화 (손) — 5부.

방송 시작/종료 때 사람처럼 공지를 올린다.
- 문구는 페르소나 말투로, 매번 다르게(기본). 단조롭지 않게.
- 새벽 시간대 게시는 피한다(설정).
- 빈도는 낮게(방송당 1회 정도) → 계정 리스크 최소화.
"""

from .base import Announcer
from .composer import AnnounceContext, compose, should_post

__all__ = ["Announcer", "AnnounceContext", "compose", "should_post"]
