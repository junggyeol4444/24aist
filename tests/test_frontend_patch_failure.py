"""웹UI 주소 패치가 실패하면 실패라고 말하는지.

이 패치가 안 들어가면 웹UI 는 /client-ws 로 붙는다. 그 경로는 채팅을
넣은 쪽에만 결과를 돌려주므로, AI 가 말을 해도 OBS 화면에는 아무것도
안 나온다 — 이 프로젝트에서 제일 나쁜 무음 방송이다.

프론트엔드받기.bat 과 fetch_frontend.sh 에는 "[경고] 웹UI 주소 설정을
못 넣었습니다" 가 적혀 있었는데, main() 이 실패해도 항상 0 을 돌려줘서
그 경고가 영영 뜨지 않았다. 운영자는 "완료" 만 보고 넘어간다.
"""

import subprocess
import sys

import pytest

from aist.frontend_patch import MARK, is_patched, main, patch_index

_REAL = ('<html><head><title>Open-LLM-VTuber</title></head>'
         '<body><script type="module" crossorigin src="/assets/index.js">'
         '</script></body></html>')


def _write(tmp_path, html, name="index.html"):
    (tmp_path / name).write_text(html, encoding="utf-8")
    return tmp_path


def test_정상이면_0(tmp_path, capsys):
    _write(tmp_path, _REAL)
    assert main([str(tmp_path)]) == 0
    assert is_patched(tmp_path / "index.html")


def test_구조를_못_알아보면_1(tmp_path, capsys):
    _write(tmp_path, "<div>그냥 텍스트</div>")
    assert main([str(tmp_path)]) == 1
    assert "[실패]" in capsys.readouterr().out


def test_파일이_없으면_1(tmp_path, capsys):
    assert main([str(tmp_path)]) == 1
    assert "[실패]" in capsys.readouterr().out


def test_쓰지_못하면_트레이스백_대신_사유(tmp_path):
    _write(tmp_path, _REAL)
    (tmp_path / "index.html").chmod(0o444)
    tmp_path.chmod(0o555)
    try:
        msg = patch_index(tmp_path)
    finally:
        tmp_path.chmod(0o755)
        (tmp_path / "index.html").chmod(0o644)
    if msg.startswith("[실패]"):          # root 로 돌면 권한이 안 먹는다
        assert "쓰지 못했습니다" in msg


def test_두_번_넣어도_한_번만(tmp_path):
    _write(tmp_path, _REAL)
    main([str(tmp_path)])
    main([str(tmp_path)])
    html = (tmp_path / "index.html").read_text(encoding="utf-8")
    assert html.count(f'id="{MARK}"') == 1


def test_배치가_보는_종료코드(tmp_path):
    """프론트엔드받기.bat 은 errorlevel 로만 판단한다 — 실제 프로세스로 확인."""
    (tmp_path / "index.html").write_text("<div>못 알아봄</div>", encoding="utf-8")
    r = subprocess.run([sys.executable, "-m", "aist.frontend_patch", str(tmp_path)],
                       capture_output=True, text=True)
    assert r.returncode == 1, r.stdout + r.stderr
