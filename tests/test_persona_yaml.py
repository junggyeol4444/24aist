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
