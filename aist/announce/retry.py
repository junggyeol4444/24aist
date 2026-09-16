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
# 서버가 이보다 오래 기다리라고 하면 공지를 포기한다.
# (방송 시작을 몇 분씩 붙잡느니 공지를 거르는 게 낫다)
MAX_WAIT_SEC = 30.0
# 재시도해도 의미 없는 상태 코드(설정·권한 문제)
_PERMANENT = {400, 401, 403, 404, 405, 413}


def should_retry_status(status: Optional[int]) -> bool:
    """이 응답 코드로 다시 시도할 만한지."""
    if status is None:          # 네트워크 예외 — 다시 해볼 만하다
        return True
    if status in _PERMANENT:
        return False
    return status == 429 or status >= 500


def retry_after_of(r) -> Optional[float]:
    """응답이 알려준 대기 시간(초). 없거나 못 읽으면 None.

    헤더 Retry-After(초)와 본문 retry_after(초) 중 큰 값을 쓴다 — 더 짧게
    잡았다가 먼저 보내면 레이트 리밋 위반으로 세어져 계정·IP 가 더 오래
    막힌다. 여기서 예외가 나면 바깥이 네트워크 오류로 오인해 재시도하면
    안 될 4xx 까지 다시 보내게 되므로, 무슨 일이 있어도 던지지 않는다.
    """
    vals = []
    headers = getattr(r, "headers", None) or {}
    try:
        head = headers.get("Retry-After")
    except Exception:  # noqa: BLE001
        head = None
    if head:
        try:
            vals.append(float(head))
        except (TypeError, ValueError):
            pass
    try:
        body = r.json()
        if isinstance(body, dict) and body.get("retry_after") is not None:
            vals.append(float(body["retry_after"]))
    except Exception:  # noqa: BLE001 - 본문이 JSON 이 아닐 수 있다
        pass
    return max(vals) if vals else None


def post_with_retry(
    send: Callable[[], tuple],
    *,
    what: str,
    attempts: int = DEFAULT_ATTEMPTS,
    backoff_sec: float = DEFAULT_BACKOFF_SEC,
    max_wait_sec: float = MAX_WAIT_SEC,
    sleep: Callable[[float], None] = time.sleep,
) -> bool:
    """send() 를 성공할 때까지(또는 재시도 가치가 없을 때까지) 부른다.

    send 는 (성공여부, 상태코드, 사람이 읽는 사유) 또는 거기에
    (서버가 알려준 대기 초) 를 더한 4개짜리를 돌려준다.
    상태코드가 None 이면 네트워크 예외로 본다.

    서버가 "이만큼 기다려라"(Retry-After)고 하면 그 말을 따른다. 우리가
    정한 간격이 더 짧다고 먼저 보내면, 레이트 리밋을 어긴 것으로 세어져
    계정·IP 가 더 오래 막힌다. 다만 그 시간이 상한보다 길면 기다리지 않고
    포기한다 — 공지 한 줄 때문에 방송 시작을 몇 분씩 붙잡아 둘 수는 없다.
    """
    attempts = max(1, attempts)
    for i in range(1, attempts + 1):
        result = send()
        ok, status, detail = result[0], result[1], result[2]
        asked = result[3] if len(result) > 3 else None
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
        if asked is not None and asked > 0:
            if asked > max_wait_sec:
                log.error("%s 게시 실패 (%s): 서버가 %.0f초 기다리라고 합니다 — "
                          "그보다 먼저 보내면 더 오래 막히고, 그만큼 기다리면 "
                          "방송이 밀립니다. 이번 공지는 포기합니다.",
                          what, status, asked)
                return False
            wait = max(wait, asked)
        log.warning("%s 게시 실패 (%s): %s — %.0f초 뒤 다시 시도합니다 (%d/%d)",
                    what, status, detail, wait, i, attempts)
        sleep(wait)
    return False
