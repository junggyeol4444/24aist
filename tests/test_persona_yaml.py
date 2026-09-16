"""persona.yaml 을 손으로 고치다 형식이 어긋나도 캐릭터가 망가지면 안 된다.

운영자는 이 파일을 메모장으로 직접 고친다(기획안 3단계). 목록을 한 줄로
적는 실수는 YAML 에서 가장 흔하다.
"""

from pathlib import Path

import pytest

from aist.persona import Persona


def test_list_written_as_one_line_is_not_split_into_letters():
    """예전에는 '밝음' 이 글자 단위로 쪼개져 "성격: 밝, 음." 이 됐다."""
    p = Persona.from_dict({"name": "별이", "personality": "밝음"})
    prompt = p.render_system_prompt()
    assert "성격: 밝음." in prompt
    assert "밝, 음" not in prompt
    assert p.problems, "고쳐 쓴 사실을 알려야 한다"


def test_dict_field_written_as_list_does_not_crash():
    """예전에는 AttributeError 로 프로그램이 죽었다."""
    p = Persona.from_dict({"reaction_directions": ["악플", "무시"]})
    p.render_system_prompt()
    assert any("reaction_directions" in n for n in p.problems)


def test_empty_name_does_not_become_none():
    p = Persona.from_dict({"name": None})
    assert "'None'" not in p.render_system_prompt()
    assert p.name == "별이"


def test_unknown_key_is_reported_with_suggestion():
    p = Persona.from_dict({"nmae": "별이"})
    assert any("nmae" in n and "name" in n for n in p.problems)


def test_normal_persona_has_no_complaints():
    from aist.persona import _example_persona
    p = Persona.from_dict(_example_persona())
    assert p.problems == []
    prompt = p.render_system_prompt()
    assert "성격: 밝음, 장난기 많음" in prompt


def test_shipped_example_persona_is_clean():
    root = Path(__file__).resolve().parents[1]
    for name in ("config/persona.example.yaml", "persona.yaml"):
        f = root / name
        if f.exists():
            assert Persona.load(f).problems == [], f"{name} 에 형식 문제가 있습니다"


# ---------------- persona.yaml 을 고쳐도 방송에 반영이 안 되던 것 ----------------
def test_core_persona_mismatch_is_reported(tmp_path):
    """방송인의 성격은 코어 conf.yaml 안에 박혀 있다.

    persona.yaml 만 고치고 build-persona 를 안 돌리면 방송에는 하나도
    반영되지 않는데, 아무도 알려주지 않았다.
    """
    from aist.preflight import persona_applied_to_core

    core = tmp_path / "Open-LLM-VTuber"
    core.mkdir()
    (core / "conf.yaml").write_text(
        "character_config:\n  persona_prompt: |-\n    너는 '별이'다.\n",
        encoding="utf-8")

    ok, msg = persona_applied_to_core("너는 '별이'다.", tmp_path)
    assert ok is True, msg

    ok, msg = persona_applied_to_core("너는 '달이'다.", tmp_path)
    assert ok is False and "반영" in msg
    assert "build-persona" in msg or "페르소나적용" in msg


def test_persona_apply_bat_exists():
    """윈도우 사용자는 명령을 못 친다 — 더블클릭할 파일이 있어야 한다."""
    from pathlib import Path

    bat = Path(__file__).resolve().parents[1] / "windows" / "페르소나적용.bat"
    assert bat.is_file()
    text = bat.read_bytes().decode("utf-8")
    assert "build-persona" in text
    assert not bat.read_bytes().startswith(b"\xef\xbb\xbf")


def test_missing_persona_file_is_loud(tmp_path, monkeypatch, capsys):
    """persona.yaml 이 없으면 기본 캐릭터로 도는데, 조용히 그러면 안 된다."""
    import argparse

    import aist.cli as cli

    cfg_path = tmp_path / "c.yaml"
    cfg_path.write_text("platform: rehearsal\n", encoding="utf-8")
    cfg, persona = cli._load(argparse.Namespace(
        config=str(cfg_path), persona=str(tmp_path / "없는파일.yaml")))
    assert any("페르소나 파일이 없습니다" in n for n in persona.problems)
