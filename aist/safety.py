"""사고 방지 장치 — 시청자 입력 소독, 발화 점검, 즉시 중단 플래그.

기획안 8-2 가 인정한 "돌발 발언" 과, 24시간 무인 운영에서 사람이 자리에
없는 시간을 위한 최소 장치다. 무엇이 금지어인지는 **운영자가 정한다**
(기본값은 빈 목록 — 코드가 미리 정하지 않는다, 기획안 3-3/3-5).

세 가지만 한다:
  1) sanitize_incoming  — 시청자 채팅/닉네임을 코어에 넘기기 전에 소독
  2) check_output       — AI 가 실제로 말한 문장을 운영자 금지어와 대조
  3) StopFlag           — 파일 하나로 라이브를 즉시 멈추는 스위치

1) 이 필요한 이유:
  운영자 지시(매니저 귓속말)와 시청자 채팅이 같은 text-input 채널로 나간다.
  소독이 없으면 시청자가 개행을 넣어 진짜 시스템 신호와 **구별 불가능한
  줄**을 만들 수 있다(실제로 재현됨). 개행·제어문자를 없애면 시청자 입력은
  언제나 "닉: 내용" 한 줄 안에 갇힌다.
"""

import logging
import re
import unicodedata
from pathlib import Path
from typing import List, Optional

log = logging.getLogger("aist.safety")

# 시스템 신호를 흉내내는 문구 — 시청자 입력에서는 무력화한다.
# (운영자 지시는 이 표현을 쓰고, 시청자는 못 쓰게 해서 경계를 만든다)
_CUE_MARKERS = ("매니저 귓속말", "매니저귓속말", "manager whisper",
                "게임 상황", "게임상황")

# 코어에 넘기는 채팅 한 줄의 상한. 지나치게 긴 입력으로 앞의 지시를
# 밀어내는 것(컨텍스트 밀어내기)을 막는다.
MAX_CHAT_CHARS = 500
MAX_AUTHOR_CHARS = 60


def _strip_control(s: str) -> str:
    """개행·탭·제로폭 등 제어/포맷 문자를 공백으로 바꾸고 공백을 정리한다.

    개행 제거가 핵심이다. 채팅이 여러 줄이 되면 시스템 신호와 같은 모양의
    줄을 만들 수 있다.
    """
    if not s:
        return ""
    out = []
    for ch in s:
        cat = unicodedata.category(ch)
        # Cc 제어, Cf 포맷(제로폭·RTL 등), Zl/Zp 줄/문단 구분
        if cat in ("Cc", "Cf", "Zl", "Zp"):
            out.append(" ")
        else:
            out.append(ch)
    return re.sub(r"\s+", " ", "".join(out)).strip()


def _defang_markers(s: str) -> str:
    """시스템 신호 흉내 문구를 무력화한다(지우지 않고 표시만 깬다)."""
    for m in _CUE_MARKERS:
        if m in s:
            # 가운데에 보이지 않는 구분을 넣는 대신, 사람이 읽어도 자연스럽고
            # 신호로는 안 읽히는 형태로 바꾼다.
            s = s.replace(m, "매니저 얘기" if "매니저" in m or "manager" in m
                          else "게임 얘기")
            log.warning("채팅에서 시스템 신호 흉내 문구를 무력화했습니다.")
    return s


def sanitize_incoming(text: str, author: str = "") -> tuple:
    """시청자 채팅과 닉네임을 코어에 넘기기 전에 소독한다.

    반환: (소독된 text, 소독된 author)
    채팅을 버리지 않는다(기획안 1-2: 다 읽고 다 반응). 모양만 가둔다.
    """
    t = _defang_markers(_strip_control(text))[:MAX_CHAT_CHARS]
    a = _defang_markers(_strip_control(author))[:MAX_AUTHOR_CHARS]
    # 닉네임에 콜론이 있으면 "닉: 내용" 형식을 흉내낼 수 있다.
    a = a.replace(":", " ")
    return t, a


def check_output(text: str, banned: List[str]) -> Optional[str]:
    """AI 발화에 운영자가 정한 금지어가 있으면 그 단어를 돌려준다.

    banned 가 비어 있으면(기본값) 아무것도 하지 않는다 — 무엇이 문제인지는
    운영자가 방송을 보고 정한다.
    """
    if not text or not banned:
        return None
    low = text.lower()
    for w in banned:
        w = (w or "").strip()
        if w and w.lower() in low:
            return w
    return None


class StopFlag:
    """파일 하나로 도는 즉시 중단 스위치.

    `aist stop` 이 이 파일을 만들고, 방송 루프가 매 주기 확인해서 보이면
    정상 종료 절차(마무리 → OBS 내리기 → 기록 저장)로 들어간다.
    프로세스 간 통신이 필요 없어 윈도우/리눅스 어디서나 같게 동작하고,
    사람이 자리에 없어도(원격 파일 동기화 등) 쓸 수 있다.
    """

    def __init__(self, path: str):
        self.path = Path(path)

    def raised(self) -> bool:
        try:
            return self.path.exists()
        except OSError:
            return False

    def raise_(self, reason: str = "") -> Path:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(reason or "stop", encoding="utf-8")
        return self.path

    def clear(self) -> None:
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass
        except OSError as e:
            log.warning("중단 플래그 삭제 실패: %s", e)

    def reason(self) -> str:
        try:
            return self.path.read_text(encoding="utf-8").strip()
        except OSError:
            return ""


def header_safe(value: str) -> bool:
    """이 값이 HTTP 헤더에 실릴 수 있는지(latin-1).

    토큰에 한글이나 따옴표가 섞이면(메모장에서 라벨까지 같이 붙여넣는
    실수가 흔하다) 요청이 나가지도 못하고
      'latin-1' codec can't encode characters in position ...
    만 반복된다. 운영자가 그 메시지로 고칠 방법은 없다.
    """
    try:
        (value or "").encode("latin-1")
        return True
    except UnicodeEncodeError:
        return False


def token_problem(name: str, value: str) -> Optional[str]:
    """토큰 값이 못 쓸 모양이면 사람이 읽는 사유를 돌려준다."""
    if not value:
        return None
    if not header_safe(value):
        return (f"{name} 에 보낼 수 없는 문자가 섞여 있습니다(한글·따옴표 등) — "
                f".env 에서 토큰 값만 남도록 다시 붙여넣으세요.")
    if value != value.strip():
        return f"{name} 앞뒤에 공백이 있습니다 — 값만 남도록 다시 붙여넣으세요."
    return None
