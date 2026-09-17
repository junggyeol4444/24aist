"""중복 실행 방지 — 같은 설정으로 방송을 두 번 켜지 못하게 한다.

운영자는 바탕화면 아이콘을 더블클릭한다. 이미 돌고 있는 걸 모르고 한 번
더 누르는 일이 실제로 생긴다(무인운영이 도는 중에 방송시작을 누르는 경우도
같다). 그러면:
  - 채팅 한 줄이 코어에 두 번 들어가서 AI 가 같은 말을 두 번 한다
  - 먼저 끝난 쪽이 OBS 송출을 내려서, 아직 방송 중인 쪽의 화면이 꺼진다
  - 종료 공지도 두 번 나간다

파일 잠금으로 막는다. 파일이 '있는지'가 아니라 OS 잠금을 쓰는 이유는,
프로세스가 강제 종료돼도 잠금은 OS 가 바로 풀어주기 때문이다(파일만
남기는 방식은 강제 종료 뒤 영영 실행이 안 되는 상태가 된다).

잠금 파일 경로는 설정의 stop_flag_path 옆에 둔다 — 설정 파일을 따로
쓰는 두 방송(채널이 다른 경우)은 서로 막지 않는다.
"""

import logging
import os
from pathlib import Path
from typing import Optional

log = logging.getLogger("aist.single")

# 잡은 파일 핸들을 여기에 붙들어 둔다. 호출자가 InstanceLock 객체를
# 변수에 안 담으면 가비지 컬렉션이 파일을 닫고, 그 순간 OS 가 잠금을
# 풀어버린다 — 잠금이 있는데 없는 것처럼 동작한다.
_HELD = []


def lock_path_for(stop_flag_path: str) -> Path:
    return Path(stop_flag_path).parent / "RUNNING.lock"


class InstanceLock:
    """획득하면 프로세스가 살아 있는 동안 유지되는 잠금."""

    def __init__(self, path):
        self.path = Path(path)
        self._fh = None

    def acquire(self) -> bool:
        """잠금을 잡으면 True, 이미 다른 프로세스가 쥐고 있으면 False.

        잠금 자체가 불가능한 환경(권한·파일시스템 문제)에서는 방송을
        막지 않는다 — 중복 실행보다 '아예 못 켬' 이 더 나쁘다.
        """
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fh = open(self.path, "a+b")
        except OSError as e:
            log.warning("중복 실행 잠금 파일을 못 열었습니다(%s) — 확인 없이 진행합니다", e)
            return True
        try:
            if os.name == "nt":
                import msvcrt
                fh.seek(0)
                msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            fh.close()
            return False
        except Exception as e:  # noqa: BLE001 - 잠금 미지원 환경
            log.warning("중복 실행 확인을 못 했습니다(%s) — 확인 없이 진행합니다", e)
            fh.close()
            return True
        self._fh = fh
        _HELD.append(fh)
        return True

    def release(self) -> None:
        fh, self._fh = self._fh, None
        if fh is None:
            return
        try:
            _HELD.remove(fh)
        except ValueError:
            pass
        try:
            if os.name == "nt":
                import msvcrt
                fh.seek(0)
                msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        finally:
            try:
                fh.close()
            except OSError:
                pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.release()
        return False
