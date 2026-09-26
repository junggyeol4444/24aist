"""RVC 목소리 변조 훅(AIST_TTS_POST_CMD)이 윈도우 경로에서 매번 실패하던 것.

예전에는 POSIX 방식으로 명령을 쪼개서 역슬래시가 사라졌다. 윈도우
파이썬(Wine)으로 실제로 돌려 보니:
  old ['Z:tmpwpostrvcconvert.bat', ...] → FileNotFoundError, 목소리 그대로
  new ['cmd', '/c', 'Z:\\tmp\\wpost\\rvc\\convert.bat', ...] → 변환됨
경고 한 줄만 남기고 원본 목소리로 방송이 나가서 운영자는 몰랐다.

코어 모듈은 CI 에 없는 패키지를 쓰므로 함수만 떼어 실행한다.
"""
import ast
from pathlib import Path

_SRC = (Path(__file__).resolve().parents[1] / "Open-LLM-VTuber" / "src"
        / "open_llm_vtuber" / "conversations" / "tts_manager.py")


def _load(monkeypatch, osname):
    tree = ast.parse(_SRC.read_text(encoding="utf-8"))
    fn = next(n for n in tree.body
              if isinstance(n, ast.FunctionDef) and n.name == "post_cmd_args")
    ns = {}
    exec(compile(ast.Module(body=[fn], type_ignores=[]), str(_SRC), "exec"), ns)
    import os
    monkeypatch.setattr(os, "name", osname)
    return ns["post_cmd_args"]


def test_윈도우_경로의_역슬래시가_살아_있다(monkeypatch):
    f = _load(monkeypatch, "nt")
    assert f(r"C:\rvc\convert.exe {in}", r"C:\cache\a.wav") == [
        r"C:\rvc\convert.exe", r"C:\cache\a.wav"]


def test_윈도우_배치파일은_cmd_로_돌린다(monkeypatch):
    f = _load(monkeypatch, "nt")
    assert f(r'"C:\my tools\rvc.bat" --in {in}', r"C:\a.wav") == [
        "cmd", "/c", r"C:\my tools\rvc.bat", "--in", r"C:\a.wav"]


def test_리눅스는_예전과_같다(monkeypatch):
    f = _load(monkeypatch, "posix")
    assert f("bash /opt/rvc.sh {in}", "/tmp/a.wav") == ["bash", "/opt/rvc.sh", "/tmp/a.wav"]
    assert f("bash /opt/rvc.sh", "/tmp/a.wav") == ["bash", "/opt/rvc.sh", "/tmp/a.wav"]
