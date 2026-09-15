"""중복 실행 방지.

운영자가 아이콘을 두 번 누르는 일은 실제로 생긴다. 두 개가 같이 돌면
AI 가 채팅마다 두 번 말하고, 먼저 끝난 쪽이 OBS 송출을 내려 아직 방송
중인 쪽 화면이 꺼진다.
"""

import subprocess
import sys
import textwrap

from aist.single_instance import InstanceLock, lock_path_for


def _child(path: str) -> str:
    """별도 프로세스에서 같은 잠금을 잡아본다(같은 프로세스면 의미 없음)."""
    code = textwrap.dedent(f"""
        import sys
        sys.path.insert(0, {repr(sys.path[0])})
        from aist.single_instance import InstanceLock
        print("ACQUIRED" if InstanceLock({path!r}).acquire() else "BUSY")
    """)
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    return r.stdout.strip()


def test_second_process_is_refused(tmp_path):
    p = tmp_path / "RUNNING.lock"
    lock = InstanceLock(p)
    assert lock.acquire() is True
    assert _child(str(p)) == "BUSY"
    lock.release()
    assert _child(str(p)) == "ACQUIRED"   # 끝나면 다시 켤 수 있어야 한다


def test_lock_file_is_created_next_to_stop_flag():
    assert lock_path_for("data/STOP").name == "RUNNING.lock"
    assert str(lock_path_for("data/STOP").parent) == "data"
    # 설정 파일이 다르면(채널이 다르면) 서로 막지 않는다
    assert lock_path_for("data2/STOP") != lock_path_for("data/STOP")


def test_hard_kill_releases_the_lock(tmp_path):
    """강제 종료(작업관리자로 끝내기) 뒤에도 다시 켤 수 있어야 한다.

    '파일이 있으면 실행 중' 방식이었다면 여기서 영영 못 켜는 상태가 된다.
    """
    p = tmp_path / "RUNNING.lock"
    code = textwrap.dedent(f"""
        import sys, time
        sys.path.insert(0, {repr(sys.path[0])})
        from aist.single_instance import InstanceLock
        InstanceLock({str(p)!r}).acquire()
        print("HELD", flush=True)
        time.sleep(30)
    """)
    proc = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE,
                            text=True)
    try:
        assert proc.stdout.readline().strip() == "HELD"
        assert _child(str(p)) == "BUSY"
        proc.kill()
        proc.wait(timeout=10)
    finally:
        if proc.poll() is None:
            proc.kill()
    assert _child(str(p)) == "ACQUIRED"


def test_unlockable_path_does_not_block_broadcast(tmp_path, monkeypatch):
    """잠금을 못 잡는 환경에서 '아예 못 켬' 이 되면 안 된다."""
    import aist.single_instance as si

    lock = InstanceLock(tmp_path / "x.lock")
    monkeypatch.setattr(si.Path, "mkdir",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("권한 없음")))
    assert lock.acquire() is True     # 경고만 하고 진행
