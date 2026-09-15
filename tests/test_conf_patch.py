"""코어 conf.yaml 을 고칠 때 설명 주석을 지우지 않는다.

코어 conf.yaml 은 설명 주석이 빽빽한 파일이고, 운영자가 거기서 LLM 키와
TTS 경로를 직접 채워야 한다. safe_load → safe_dump 로 다시 쓰면 그 설명이
전부 사라진다(실제로 conf.korean.yaml 이 주석 0줄이었다).
"""

from pathlib import Path

import pytest
import yaml

from aist.conf_patch import ConfPatchError, set_value

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "Open-LLM-VTuber" / "config_templates" / "conf.default.yaml"
KOREAN = ROOT / "Open-LLM-VTuber" / "conf.korean.yaml"

SAMPLE = """\
# 맨 위 설명
system_config:
  port: 12393   # 포트 설명
character_config:
  conf_name: 'mao'  # 이름 설명
  # 페르소나 설명
  persona_prompt: |
    old line 1
    old line 2

  tts_config:
    tts_model: 'edge_tts'
"""


def _comments(text):
    return [l for l in text.split("\n") if l.strip().startswith("#")]


def test_block_value_replaced_and_comments_kept():
    out = set_value(SAMPLE, ["character_config", "persona_prompt"], "새 줄1\n새 줄2")
    assert len(_comments(out)) == len(_comments(SAMPLE))
    d = yaml.safe_load(out)
    assert d["character_config"]["persona_prompt"] == "새 줄1\n새 줄2"
    assert d["character_config"]["tts_config"]["tts_model"] == "edge_tts"
    assert d["system_config"]["port"] == 12393


def test_nested_scalar_keeps_trailing_comment():
    out = set_value(SAMPLE, ["character_config", "tts_config", "tts_model"], "gpt_sovits_tts")
    assert yaml.safe_load(out)["character_config"]["tts_config"]["tts_model"] == "gpt_sovits_tts"
    assert "# 이름 설명" in out
    out2 = set_value(SAMPLE, ["character_config", "conf_name"], "kr_별이")
    assert "# 이름 설명" in out2      # 값 옆 설명도 살린다
    assert yaml.safe_load(out2)["character_config"]["conf_name"] == "kr_별이"


def test_missing_key_is_an_error_not_a_silent_noop():
    with pytest.raises(ConfPatchError):
        set_value(SAMPLE, ["character_config", "없는키"], "x")


def test_same_value_is_allowed():
    out = set_value(SAMPLE, ["character_config", "conf_name"], "mao")
    assert yaml.safe_load(out)["character_config"]["conf_name"] == "mao"


@pytest.mark.skipif(not KOREAN.exists() or not TEMPLATE.exists(),
                    reason="코어가 없는 환경")
def test_korean_conf_still_has_the_explanations():
    """한국어 conf 가 다시 주석 없는 파일이 되면 안 된다."""
    kr = KOREAN.read_text(encoding="utf-8")
    tmpl = TEMPLATE.read_text(encoding="utf-8")
    assert len(_comments(kr)) >= len(_comments(tmpl)) * 0.9, "설명 주석이 사라졌습니다"
    # 설정 항목은 템플릿과 같은 구조여야 한다(코어가 읽는 키가 빠지면 안 됨)
    def keys(d, p=""):
        out = set()
        for k, v in (d or {}).items():
            out.add(p + str(k))
            if isinstance(v, dict):
                out |= keys(v, f"{p}{k}.")
        return out
    assert keys(yaml.safe_load(kr)) == keys(yaml.safe_load(tmpl))
