"""공지 게시 재시도.

공지는 방송당 한두 번뿐인데, 그 한 번이 네트워크 순단으로 실패하면
시청자는 방송이 켜진 걸 모른다(기획안 2-2② 의 기본 동선이 통째로 빠진다).
그런데 지금까지는 한 번 실패하면 끝이었다.

재시도 대상과 아닌 것을 구분한다:
  재시도함   — 네트워크 오류, 5xx(서버 문제), 429(레이트 리밋)
  재시도 안 함 — 4xx(설정/권한 문제). 채널 ID 가 틀렸거나 토큰이 죽은
                 것이라 다시 보내도 똑같이 실패한다. 로그로 알리는 게 낫다.

플랫폼 계정 리스크를 생각해 횟수는 짧게 둔다(기획안 5-2 "빈도 낮게").
"""

import logging
import time
from typing import Callable, Optional

log = logging.getLogger("aist.announce.retry")

DEFAULT_ATTEMPTS = 3
DEFAULT_BACKOFF_SEC = 2.0
# 재시도해도 의미 없는 상태 코드(설정·권한 문제)
_PERMANENT = {400, 401, 403, 404, 405, 413}


def should_retry_status(status: Optional[int]) -> bool:
    """이 응답 코드로 다시 시도할 만한지."""
    if status is None:          # 네트워크 예외 — 다시 해볼 만하다
        return True
    if status in _PERMANENT:
        return False
    return status == 429 or status >= 500


def post_with_retry(
    send: Callable[[], tuple],
    *,
    what: str,
    attempts: int = DEFAULT_ATTEMPTS,
    backoff_sec: float = DEFAULT_BACKOFF_SEC,
    sleep: Callable[[float], None] = time.sleep,
) -> bool:
    """send() 를 성공할 때까지(또는 재시도 가치가 없을 때까지) 부른다.

    send 는 (성공여부, 상태코드, 사람이 읽는 사유) 를 돌려준다.
    상태코드가 None 이면 네트워크 예외로 본다.
    """
    attempts = max(1, attempts)
    for i in range(1, attempts + 1):
        ok, status, detail = send()
        if ok:
            if i > 1:
                log.info("%s 게시 성공 (%d번째 시도)", what, i)
            return True
        if not should_retry_status(status):
            log.error("%s 게시 실패 (%s): %s — 설정·권한 문제로 보여 "
                      "다시 시도하지 않습니다.", what, status, detail)
            return False
        if i == attempts:
            log.error("%s 게시 실패 (%s): %s — %d번 시도 후 포기합니다. "
                      "시청자에게 공지가 안 나갔습니다.", what, status, detail, attempts)
            return False
        wait = backoff_sec * i
        log.warning("%s 게시 실패 (%s): %s — %.0f초 뒤 다시 시도합니다 (%d/%d)",
                    what, status, detail, wait, i, attempts)
        sleep(wait)
    return False
