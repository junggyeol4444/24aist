from aist.persona import Persona


def test_render_includes_core_fields():
    p = Persona(
        name="별이", age_range="20대", gender="여성",
        personality=["밝음", "장난기"], speech_habits=["~거든"],
        taboos=["정치 단정"], concept="수다형",
    )
    out = p.render_system_prompt()
    assert "별이" in out
    assert "밝음" in out
    assert "~거든" in out
    assert "정치 단정" in out
    assert "수다형" in out


def test_render_does_not_impose_behavior_rules():
    """행동 규칙(딜레이/채팅 선별 강제)을 박지 않는다 — 절대 원칙."""
    out = Persona().render_system_prompt()
    assert "딜레이" not in out
    assert "일부만" not in out


def test_load_example():
    p = Persona.load("config/persona.example.yaml")
    assert p.name
    assert p.render_system_prompt()
