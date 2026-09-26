"""`aist build-persona` — 코어 conf.yaml 개조."""

import types
from pathlib import Path

import yaml

import aist.cli as cli
from aist.config import Config
from aist.persona import Persona

SAMPLE = """\
# 설명 1
character_config:
  conf_name: 'mao'
  # 페르소나 설명
  persona_prompt: |
    old
  tts_config:
    tts_model: 'edge_tts'
"""


def _args(conf, live2d=""):
    return types.SimpleNamespace(config="c", persona="p", log="INFO",
                                 conf=str(conf), live2d=live2d, out="out.txt")


def _patch_load(monkeypatch):
    monkeypatch.setattr(cli, "_load", lambda args: (Config(), Persona()))


def test_comments_survive(tmp_path, monkeypatch, capsys):
    _patch_load(monkeypatch)
    conf = tmp_path / "conf.yaml"
    conf.write_text(SAMPLE, encoding="utf-8")
    cli.cmd_build_persona(_args(conf))
    out = conf.read_text(encoding="utf-8")
    assert "# 설명 1" in out and "# 페르소나 설명" in out
    d = yaml.safe_load(out)
    assert d["character_config"]["tts_config"]["tts_model"] == "gpt_sovits_tts"
    assert "별이" in d["character_config"]["persona_prompt"] or \
        d["character_config"]["persona_prompt"] != "old\n"


def test_backup_is_not_overwritten_on_second_run(tmp_path, monkeypatch):
    _patch_load(monkeypatch)
    conf = tmp_path / "conf.yaml"
    conf.write_text(SAMPLE, encoding="utf-8")
    cli.cmd_build_persona(_args(conf))
    cli.cmd_build_persona(_args(conf))
    first = (tmp_path / "conf.yaml.bak").read_text(encoding="utf-8")
    assert "tts_model: 'edge_tts'" in first, "첫 백업이 개조본으로 덮였습니다"
    assert (tmp_path / "conf.yaml_2.bak").exists()


def test_empty_character_config_does_not_crash(tmp_path, monkeypatch):
    """손으로 고치다 'character_config:' 만 남은 파일."""
    _patch_load(monkeypatch)
    conf = tmp_path / "conf.yaml"
    conf.write_text("character_config:\n", encoding="utf-8")
    cli.cmd_build_persona(_args(conf))
    d = yaml.safe_load(conf.read_text(encoding="utf-8"))
    assert d["character_config"]["tts_config"]["tts_model"] == "gpt_sovits_tts"
    assert d["character_config"]["persona_prompt"]


def test_cp949_conf_is_readable(tmp_path, monkeypatch):
    """메모장 'ANSI' 로 저장된 conf 도 읽는다(전에는 여기서 죽었다)."""
    _patch_load(monkeypatch)
    conf = tmp_path / "conf.yaml"
    conf.write_bytes(SAMPLE.replace("# 설명 1", "# 한글 설명").encode("cp949"))
    cli.cmd_build_persona(_args(conf))
    assert conf.read_text(encoding="utf-8")
