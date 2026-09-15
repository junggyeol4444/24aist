"""주 사용 환경은 윈도우다 — 안내가 윈도우에서 칠 수 없는 명령이면 안 된다.

윈도우 사용자에게 `bash ...` / `./x.sh` / `cd A && B` 를 보여주면 그대로
막힌다. 점검이 내놓는 모든 안내는 그 OS 에서 실제로 실행 가능해야 한다.
"""

import argparse
import io
from contextlib import redirect_stdout
from pathlib import Path

import pytest

from aist import cli, preflight

# 윈도우 cmd 에서 안 먹는 것들
POSIX_ONLY = ("bash ", "./", " && ", ".sh")

WINDOWS_DIR = Path(__file__).resolve().parent.parent / "windows"


def _check_output(monkeypatch, *, windows: bool) -> str:
    monkeypatch.setattr(preflight, "IS_WINDOWS", windows)
    buf = io.StringIO()
    with redirect_stdout(buf):
        cli.cmd_check(argparse.Namespace(
            config="config/config.example.yaml",
            persona="config/persona.example.yaml",
        ))
    return buf.getvalue()


def test_windows_guidance_has_no_shell_commands(monkeypatch):
    out = _check_output(monkeypatch, windows=True)
    # 안내 줄만 본다(설정 요약에는 ws:// 같은 게 섞여 있다)
    lines = [ln for ln in out.splitlines()
             if "받기" in ln or "준비" in ln or "한 번에" in ln or "미설치" in ln]
    assert lines, "안내가 하나도 안 나왔다"
    for ln in lines:
        for bad in POSIX_ONLY:
            assert bad not in ln, f"윈도우 안내에 셸 명령이 샜다: {ln!r} ({bad!r})"


def test_windows_guidance_points_at_bat_files(monkeypatch):
    out = _check_output(monkeypatch, windows=True)
    assert ".bat" in out, "윈도우인데 .bat 안내가 없다"


def test_posix_guidance_uses_shell(monkeypatch):
    out = _check_output(monkeypatch, windows=False)
    assert "run.sh" in out or ".sh" in out


@pytest.mark.parametrize("name", [
    "설치.bat", "코어준비.bat", "프론트엔드받기.bat", "코어실행.bat",
    "점검.bat", "리허설.bat", "테스트방송.bat", "방송시작.bat",
    "전체실행.bat", "리포트.bat", "EXE만들기.bat",
])
def test_referenced_bat_exists(name):
    """안내가 가리키는 .bat 이 실제로 있어야 한다."""
    assert (WINDOWS_DIR / name).is_file(), f"windows/{name} 이 없다"


@pytest.mark.parametrize("name", [p.name for p in WINDOWS_DIR.glob("*.bat")])
def test_bat_files_are_crlf(name):
    """cmd 는 LF 만 있는 배치 파일에서 오작동할 수 있다."""
    raw = (WINDOWS_DIR / name).read_bytes()
    assert b"\r\n" in raw, f"windows/{name} 이 CRLF 가 아니다"


@pytest.mark.parametrize("name", [p.name for p in WINDOWS_DIR.glob("*.bat")])
def test_bat_files_do_not_tell_windows_users_to_run_sh(name):
    """배치 파일이 화면에 .sh 를 띄우면 안 된다.

    REM 주석(개발자용)과 도메인(astral.sh)은 사용자에게 안 보이므로 뺀다.
    보는 건 echo 로 실제 출력되는 줄뿐이다.
    """
    text = (WINDOWS_DIR / name).read_bytes().decode("utf-8")
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.lower().startswith("echo"):
            continue
        cleaned = stripped.replace("astral.sh", "")   # uv 공식 문서 주소
        assert ".sh" not in cleaned, f"windows/{name} 이 화면에 .sh 를 안내한다: {stripped!r}"


def test_windows_has_unattended_option():
    """24시간 무인 운영은 이 프로젝트의 목적이다.

    리눅스는 deploy/systemd + install.sh 가 있었는데 윈도우는 아무 수단도
    없었다. 작업 스케줄러 등록/해제가 그 자리를 채운다.
    """
    reg = WINDOWS_DIR / "자동시작등록.bat"
    off = WINDOWS_DIR / "자동시작해제.bat"
    assert reg.is_file() and off.is_file()
    text = reg.read_bytes().decode("utf-8")
    assert "schtasks" in text, "작업 스케줄러에 등록하지 않는다"

    # 등록 대상은 재시작 루프가 있는 무인운영.bat 이어야 한다.
    # 전체실행.bat 은 pause 로 끝나서 무인 상태로는 못 쓴다.
    runner = WINDOWS_DIR / "무인운영.bat"
    assert runner.is_file(), "무인운영.bat 이 없다"
    assert "무인운영.bat" in text, "등록 대상이 무인운영.bat 이 아니다"


def test_unattended_runner_restarts_and_never_pauses():
    """systemd Restart=always 대등 — 죽으면 다시 띄우고, 멈춰 서지 않는다."""
    text = (WINDOWS_DIR / "무인운영.bat").read_bytes().decode("utf-8")
    assert "goto loop" in text, "재시작 루프가 없다"
    for line in text.splitlines():
        stripped = line.strip().lower()
        # `pause` 는 사람 입력을 기다린다 — 무인 상태면 영원히 멈춘다.
        assert not stripped.startswith("pause"), "무인운영.bat 에 pause 가 있다"


def test_windows_installer_prepares_core():
    """설치.bat 이 코어 준비까지 해야 한다(리눅스 run.sh setup 과 동등)."""
    text = (WINDOWS_DIR / "설치.bat").read_bytes().decode("utf-8")
    assert "코어준비.bat" in text, "설치.bat 이 코어를 준비하지 않는다"


# --- 무인 운영에서만 드러나는 것들 ------------------------------------
# 작업 스케줄러로 도는 무인 상태에는 사람도, 콘솔 입력도 없다.
# 사람이 보는 창에서는 멀쩡한 명령이 거기서는 조용히 무너진다.

def _text(name: str) -> str:
    return (WINDOWS_DIR / name).read_bytes().decode("utf-8")


def test_unattended_delay_does_not_depend_on_timeout_alone():
    """timeout 은 stdin 이 리다이렉트되면 즉시 빠진다.

        ERROR: Input redirection is not supported, exiting the process immediately.

    무인 상태가 정확히 그 조건이다. timeout 만 믿으면 재시작 대기가
    통째로 사라지고 루프가 전속력으로 돈다. 폴백이 있어야 한다.
    """
    text = _text("무인운영.bat")
    assert ":sleep" in text, "대기 서브루틴이 없다"
    assert "ping" in text, "timeout 이 실패했을 때 쓸 폴백이 없다"


def test_unattended_launches_core_without_pause():
    """무인 상태에서 코어 창이 pause 로 서 있으면 재시작마다 창이 쌓인다."""
    launch = [ln for ln in _text("무인운영.bat").splitlines()
              if "코어실행.bat" in ln and ln.strip().startswith("start")]
    assert launch, "코어를 띄우는 줄이 없다"
    assert all("nopause" in ln for ln in launch), \
        f"코어를 nopause 없이 띄운다: {launch}"


def test_core_launcher_guards_every_pause():
    """코어실행.bat 의 pause 는 전부 NOPAUSE 를 확인해야 한다.

    가드 분기(웹UI 없음)의 pause 를 빠뜨리면 거기서 영영 멈춘다 —
    실제로 처음엔 마지막 pause 만 고쳐서 이 경로가 남아 있었다.
    """
    for line in _text("코어실행.bat").splitlines():
        stripped = line.strip()
        if "pause" not in stripped.lower():
            continue
        if stripped.startswith("REM") or "nopause" in stripped.lower():
            continue
        assert "NOPAUSE" in stripped, f"무방비 pause: {stripped!r}"


def test_autostart_does_not_require_admin():
    """/rl highest 는 관리자 권한이 있어야 등록된다.

    코어도 aist 도 승격이 필요 없는데 이걸 붙이면 일반 사용자는
    등록 자체가 거부된다.
    """
    cmds = [ln.strip() for ln in _text("자동시작등록.bat").splitlines()
            if not ln.strip().startswith("REM")]
    create = [ln for ln in cmds if ln.startswith("schtasks /create")]
    assert create, "등록 명령이 없다"
    for ln in create:
        assert "/rl highest" not in ln, f"불필요하게 관리자 권한을 요구한다: {ln!r}"
        assert "/f" in ln, f"덮어쓰기 플래그가 없다: {ln!r}"


def test_autostart_has_no_stdin_prompt():
    """choice 는 콘솔 입력이 필요하다. /f 가 이미 덮어쓰므로 물을 이유가 없다."""
    for line in _text("자동시작등록.bat").splitlines():
        stripped = line.strip()
        if stripped.startswith("REM"):
            continue
        assert not stripped.lower().startswith("choice "), f"입력을 기다린다: {stripped!r}"


@pytest.mark.parametrize("name", [p.name for p in WINDOWS_DIR.glob("*.bat")])
def test_bat_has_no_utf8_bom(name):
    """UTF-8 BOM 이 붙으면 cmd 가 첫 줄을 못 읽는다.

    BOM 이 '@echo off' 앞에 들어가면 cmd 는 그 줄을 명령으로 못 알아보고
    "is not recognized as an internal or external command" 로 죽는다.
    한글이 들어간 배치라 편집기가 BOM 을 붙이기 쉽다.
    """
    raw = (WINDOWS_DIR / name).read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf"), f"windows/{name} 에 UTF-8 BOM 이 있다"
    assert raw.lstrip().lower().startswith(b"@echo off"), \
        f"windows/{name} 첫 줄이 @echo off 가 아니다"


@pytest.mark.parametrize("name", [p.name for p in WINDOWS_DIR.glob("*.bat")])
def test_bat_declares_utf8_codepage(name):
    """한글을 출력하려면 chcp 65001 이 있어야 한다."""
    text = (WINDOWS_DIR / name).read_bytes().decode("utf-8")
    assert "chcp 65001" in text, f"windows/{name} 에 chcp 65001 이 없다"


def test_frontend_fetch_has_fallback_without_curl_and_tar():
    """curl 과 tar 는 윈도우 10 1803 이상에만 있다.

    그 이하(윈도우 7/8.1, 초기 10)에서는 둘 다 없어서 웹UI 를 아예
    못 받았다. PowerShell 은 윈도우 7 부터 있으니 그걸로 받을 길을
    남겨둔다. PowerShell 의 Expand-Archive 는 zip 만 풀 수 있어서
    tar.gz 가 아니라 zip 주소를 쓴다.
    """
    text = _text("프론트엔드받기.bat")
    assert "powershell" in text.lower(), "curl/tar 가 없을 때의 대안이 없다"
    assert "Invoke-WebRequest" in text, "PowerShell 다운로드가 없다"
    assert "Expand-Archive" in text, "PowerShell 압축 해제가 없다"
    assert ".zip" in text, "Expand-Archive 는 zip 만 푼다 — zip 주소가 필요하다"


def test_frontend_fetch_still_prefers_curl():
    """빠른 경로(curl+tar)는 남아 있어야 한다. PowerShell 은 느리다."""
    text = _text("프론트엔드받기.bat")
    assert "where curl" in text and "where tar" in text
    assert text.index("where curl") < text.lower().index("invoke-webrequest"), \
        "PowerShell 을 먼저 시도한다"


def test_installer_checks_python_version():
    """코어는 파이썬 3.10~3.12 만 지원한다(Open-LLM-VTuber/pyproject.toml).

    python.org 에서 '최신'을 받으면 그 범위 밖이다. aist 는 >=3.10 이라
    깔리고, 코어 설치만 실패한다 — 왜 실패했는지 알기 어려운 자리라
    설치 첫 단계에서 막아야 한다.
    """
    text = _text("설치.bat")
    assert "PYMIN" in text, "파이썬 버전을 파싱하지 않는다"
    assert "GEQ 13" in text, "3.13 이상을 막지 않는다"
    assert "LSS 10" in text, "3.10 미만을 막지 않는다"


# =========================================================================
# 방송을 끄는 방법 — Wine 으로 .bat 을 실제로 돌려보다 찾은 것.
#
# 윈도우에서 cmd 창을 X 로 닫으면 CTRL_CLOSE_EVENT 가 가는데 파이썬은
# 그걸 시그널로 처리하지 않는다. 정상 종료가 안 돌아 OBS 스트림이 켜진 채
# 남는다(시청자에겐 멈춘 화면이 계속 나감). 그런데 방송시작.bat 이
# "창을 닫으면 멈춥니다" 라고 그 방법을 권하고 있었다.
# =========================================================================
_RUNNING_BATS = ["방송시작.bat", "테스트방송.bat", "전체실행.bat", "리허설.bat"]


def _bat(name):
    return (WINDOWS_DIR / name).read_text(encoding="utf-8")


def test_stop_bat_exists():
    """터미널 없이 방송을 안전하게 끌 수단이 있어야 한다.

    aist stop 은 있었지만 .bat 이 없었다. README 는 "터미널 몰라도 됨"을
    표방하는데 끄는 안전한 방법만 터미널 명령이었다.
    """
    p = WINDOWS_DIR / "중단.bat"
    assert p.exists(), "중단.bat 이 없습니다"
    assert "stop" in p.read_text(encoding="utf-8")


def test_stop_bat_has_no_bom_and_is_crlf():
    raw = (WINDOWS_DIR / "중단.bat").read_bytes()
    assert raw[:3] != b"\xef\xbb\xbf"
    assert b"\r\n" in raw


@pytest.mark.parametrize("name", _RUNNING_BATS)
def test_running_bats_do_not_recommend_closing_window(name):
    """창 닫기를 '끄는 방법'으로 안내하면 안 된다."""
    text = _bat(name)
    assert "창을 닫으면 멈춥니다" not in text, (
        f"{name}: 창 닫기는 OBS 스트림을 켜진 채 남긴다"
    )


@pytest.mark.parametrize("name", _RUNNING_BATS)
def test_running_bats_point_at_stop_bat(name):
    """방송이 도는 .bat 은 안전하게 끄는 법을 알려줘야 한다."""
    assert "중단.bat" in _bat(name), f"{name}: 중단.bat 안내가 없습니다"


def test_docs_warn_about_closing_window():
    for path in (Path("README.md"), WINDOWS_DIR / "사용법.md"):
        text = path.read_text(encoding="utf-8")
        assert "중단.bat" in text, f"{path}: 중단.bat 안내 없음"
        assert "X 로 닫" in text, f"{path}: 창 닫기 경고 없음"


# =========================================================================
# cmd.exe 의 괄호 함정 — Wine 으로 설치.bat 을 처음부터 돌려보다 찾았다.
#
# if/for 의 ( ) 블록 안에서 echo 에 이스케이프 안 된 괄호를 쓰면, cmd 가
# 그 ')' 를 블록의 끝으로 읽는다. 실제 cmd.exe 에서 재현한 결과:
#
#   echo [1/5] 가상환경(.venv) 생성...
#     → [1/5] 가상환경
#       '.venv'은(는) 내부 또는 외부 명령이 아닙니다.
#       '생성...'은(는) 내부 또는 외부 명령이 아닙니다.
#
# 설치가 정상인데도 빨간 에러가 뜬다. 더 나쁜 건 코어실행.bat 의
# "웹UI(화면)가 없습니다. 코어준비.bat 을 먼저 실행하세요" 였다 —
# 정작 해야 할 안내가 에러 메시지 안에 파묻혀 운영자가 뭘 할지 모르게 된다.
# =========================================================================
def _unescaped_paren_echoes(path: Path):
    """if/for 블록 안에서 이스케이프 안 된 괄호를 쓰는 echo 줄을 찾는다."""
    import re
    out = []
    depth = 0
    for lineno, line in enumerate(path.read_text(encoding="utf-8").split("\n"), 1):
        s = line.strip()
        if depth > 0 and s.lower().startswith("echo"):
            body = s[4:].replace("^(", "").replace("^)", "")
            if "(" in body or ")" in body:
                out.append((lineno, s))
        t = re.sub(r"\^.", "", s)
        t = re.sub(r'"[^"]*"', "", t)
        depth = max(depth + t.count("(") - t.count(")"), 0)
    return out


@pytest.mark.parametrize("name", [p.name for p in sorted(WINDOWS_DIR.glob("*.bat"))])
def test_no_unescaped_parens_inside_blocks(name):
    hits = _unescaped_paren_echoes(WINDOWS_DIR / name)
    assert not hits, (
        f"{name}: if/for 블록 안 echo 의 괄호를 ^( ^) 로 이스케이프해야 합니다. "
        f"안 하면 cmd 가 블록을 거기서 끊고 뒷부분을 명령으로 실행합니다 → "
        f"{hits}"
    )


def test_detector_catches_the_original_bug(tmp_path):
    """검출기가 실제로 동작하는지 — 원래 버그 형태를 넣어 확인한다."""
    bad = tmp_path / "bad.bat"
    bad.write_text(
        '@echo off\r\n'
        'if not exist "X" (\r\n'
        '  echo [1/5] 가상환경(.venv) 생성...\r\n'
        ')\r\n', encoding="utf-8")
    assert _unescaped_paren_echoes(bad)

    good = tmp_path / "good.bat"
    good.write_text(
        '@echo off\r\n'
        'if not exist "X" (\r\n'
        '  echo [1/5] 가상환경^(.venv^) 생성...\r\n'
        ')\r\n', encoding="utf-8")
    assert not _unescaped_paren_echoes(good)


def test_block_outside_echo_parens_are_fine(tmp_path):
    """블록 밖 echo 의 괄호는 문제가 없다 — 과잉 검출하면 안 된다."""
    p = tmp_path / "ok.bat"
    p.write_text('@echo off\r\necho 이건 블록 밖이라 (괜찮다)\r\n', encoding="utf-8")
    assert not _unescaped_paren_echoes(p)


# =========================================================================
# 작업 스케줄러 기본값은 24시간 무인 운영에 맞지 않는다.
# schtasks 로 만든 작업의 기본값:
#   - 실행 시간 제한 72시간 → 3일 뒤 방송인이 강제 종료된다
#   - 배터리면 시작 안 함    → 노트북은 전원 뽑으면 안 켜진다
#   - 배터리로 바뀌면 중지   → 방송 중에 꺼진다
# 기획안 7-8 "서버에 올려두고 며칠씩 알아서 돌게" 가 3일에서 멈춘다.
# =========================================================================
def test_autostart_removes_execution_time_limit():
    t = _bat("자동시작등록.bat")
    assert "PT0S" in t, "실행 시간 제한을 해제하지 않으면 3일 뒤 작업이 종료된다"


def test_autostart_handles_battery_settings():
    t = _bat("자동시작등록.bat")
    assert "AllowStartIfOnBatteries" in t
    assert "DontStopIfGoingOnBatteries" in t


def test_autostart_does_not_stack_instances():
    """재시작 루프와 겹쳐 인스턴스가 쌓이면 방송인이 여러 개 뜬다."""
    assert "IgnoreNew" in _bat("자동시작등록.bat")


def test_autostart_still_succeeds_if_hardening_fails():
    """세부 설정 실패가 등록 자체를 실패로 만들면 안 된다 — 경고만."""
    t = _bat("자동시작등록.bat")
    assert "[경고]" in t, "실패 시 경고가 있어야 한다"
    assert "exit /b 0" in t, "harden 은 실패해도 0 을 돌려줘야 한다"


def test_autostart_tells_operator_how_to_fix_by_hand():
    """자동 설정이 실패하면 손으로 고치는 법을 알려줘야 한다."""
    t = _bat("자동시작등록.bat")
    assert "작업 스케줄러" in t and "속성" in t


# =========================================================================
# 무인운영 재시작 루프 — Wine 에서 실제로 돌려보다 다듬은 것들.
#
# 루프 자체는 돌지만, 설정이 잘못돼 켜자마자 죽으면 10초마다 같은 실패를
# 영원히 반복했다. 사람이 안 보는 자리라 아무도 모른다.
# =========================================================================
def test_unattended_backs_off_on_repeated_fast_failure():
    t = _bat("무인운영.bat")
    assert "FAST_FAILS" in t, "빠른 실패를 세지 않으면 영원히 같은 간격으로 돈다"
    assert "SLOW_WAIT" in t, "간격을 늘리는 값이 없다"


def test_unattended_tells_operator_what_to_check_when_stuck():
    """막혔을 때 화면에 뭘 봐야 하는지 남겨야 한다."""
    t = _bat("무인운영.bat")
    assert "점검.bat" in t
    assert "aist.log" in t


def test_unattended_does_not_parse_locale_dependent_time():
    """%time% 을 잘라 쓰면 로캘에 따라 깨진다.

    한국어 윈도우는 "오후 3:52:10", 12시간제면 "3:52:10 AM" 이라
    %T:~0,2% 같은 자릿수 파싱이 엉뚱한 값을 만든다.
    (Wine 에서 실제로 빈 값이 나오는 걸 확인하고 고쳤다)
    """
    t = _bat("무인운영.bat")
    assert "%time:~" not in t and "%T:~" not in t, \
        "시각을 자릿수로 자르면 로캘에 따라 깨진다"


def test_unattended_survives_missing_powershell():
    """시각을 못 재면 실패 횟수를 세지 않아야 한다.

    잘못 세면 멀쩡히 도는 방송의 재시도 간격을 5분으로 늘려버린다.
    """
    t = _bat("무인운영.bat")
    assert 'if "%START_SEC%"=="0" goto :skip_count' in t
    assert ":skip_count" in t


def test_unattended_still_has_no_pause():
    """무인 자리에 pause 가 하나라도 있으면 창이 영영 서 있는다."""
    t = _bat("무인운영.bat")
    for line in t.split("\n"):
        s = line.strip().lower()
        assert not (s == "pause" or s.startswith("pause ")), \
            f"무인운영.bat 에 pause 가 있습니다: {line}"
