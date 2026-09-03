"""윈도우에서 출력이 콘솔이 아닐 때 죽지 않아야 한다.

stdout 이 콘솔이면 파이썬이 유니코드 API 로 쓰지만, 파일/파이프로
리다이렉트되면 로케일 인코딩을 쓴다. 한국어 윈도우는 cp949 이고,
안내문에 쓰는 em dash(U+2014)는 cp949 에 없다. 무인 운영은 콘솔 없이
도는 자리라 정확히 이 조건이다.
"""

import io
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent


def test_em_dash_is_not_encodable_in_cp949():
    """전제 확인 — 이게 깨지면 이 테스트들의 의미가 없다."""
    with pytest.raises(UnicodeEncodeError):
        "—".encode("cp949")


def test_fix_output_encoding_survives_replaced_stream(monkeypatch):
    """reconfigure 가 없는 스트림(테스트 캡처 등)에서도 죽지 않아야 한다."""
    from aist import cli

    monkeypatch.setattr(sys, "stdout", io.StringIO())
    monkeypatch.setattr(sys, "stderr", io.StringIO())
    cli._fix_output_encoding()          # 예외가 안 나면 통과


@pytest.mark.parametrize("cmd", [["check"], ["plan"], ["announce-preview"]])
def test_cli_does_not_crash_under_cp949_output(cmd, tmp_path):
    """cp949 로 출력이 나가도 UnicodeEncodeError 로 죽으면 안 된다."""
    env = {
        "PATH": "/usr/bin:/bin:/usr/local/bin",
        "PYTHONIOENCODING": "cp949",
        "PYTHONPATH": str(REPO),
    }
    r = subprocess.run(
        [sys.executable, str(REPO / "run_aist.py"),
         "--config", str(REPO / "config/config.example.yaml"),
         "--persona", str(REPO / "config/persona.example.yaml"), *cmd],
        capture_output=True, text=True, env=env, cwd=str(REPO), timeout=120,
    )
    combined = r.stdout + r.stderr
    assert "UnicodeEncodeError" not in combined, combined[-500:]
    assert "Traceback" not in combined, combined[-500:]
