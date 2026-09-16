"""페르소나 (3부) — "이 방송인은 누구인가"를 잡는다.

중요: 여기서는 캐릭터(말투·성격·배경)만 정의한다. "딜레이 넣어라/채팅
일부만 답해라" 같은 행동 규칙은 넣지 않는다. 그건 운영자가 방송 보고
그때그때 지시할 영역이다.

이 모듈의 결과물(render_system_prompt)은 Open-LLM-VTuber 의
character_config.persona_prompt 에 그대로 들어간다.
"""

import difflib
import logging
import os
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Dict, List, Union

import yaml

log = logging.getLogger("aist.persona")


def _as_list(key, value):
    """목록이어야 하는 항목. 한 줄로 적었으면 한 항목으로 본다."""
    if value is None:
        return [], None
    if isinstance(value, str):
        return [value], (f"'{key}' 는 목록인데 한 줄로 적혀 있습니다 "
                         f"— 한 항목으로 봅니다. 여러 개면 '- ' 로 나열하세요.")
    if isinstance(value, dict):
        return [f"{k}: {v}" for k, v in value.items()], (
            f"'{key}' 는 목록인데 항목:값 형태로 적혀 있습니다 — 줄로 폅니다.")
    if isinstance(value, (list, tuple)):
        return [str(v) for v in value if v is not None], None
    return [str(value)], f"'{key}' 형식이 예상과 달라 한 항목으로 봅니다."


def _as_dict(key, value):
    """항목:값 형태여야 하는 항목."""
    if value is None:
        return {}, None
    if isinstance(value, dict):
        return {str(k): str(v) for k, v in value.items()}, None
    if isinstance(value, (list, tuple)):
        return {}, (f"'{key}' 는 '상황: 방향' 형태여야 하는데 목록으로 "
                    f"적혀 있습니다 — 무시합니다.")
    return {}, f"'{key}' 형식이 예상과 달라 무시합니다."


def _as_text(key, value, default):
    """한 줄 문자열 항목."""
    if value is None:
        return default, (f"'{key}' 에 값이 없습니다 — 기본값({default!r})을 씁니다."
                         if default else None)
    if isinstance(value, str):
        return value, None
    if isinstance(value, (list, tuple)):
        return " ".join(str(v) for v in value), (
            f"'{key}' 는 한 줄인데 목록으로 적혀 있습니다 — 이어 붙입니다.")
    return str(value), None


@dataclass
class Persona:
    name: str = "별이"
    age_range: str = "20대 초반"
    gender: str = "여성"
    personality: List[str] = field(default_factory=list)   # 형용사 3~4개
    speech_habits: List[str] = field(default_factory=list)  # 말버릇/추임새/어미
    likes: List[str] = field(default_factory=list)
    dislikes: List[str] = field(default_factory=list)
    taboos: List[str] = field(default_factory=list)         # 절대 안 하는 말/주제
    background: str = ""
    concept: str = ""                                       # 수다형/게임형 등
    # 상황별 반응 '방향'만 (세세한 강제 아님, 선택)
    reaction_directions: Dict[str, str] = field(default_factory=dict)
    example_lines: List[str] = field(default_factory=list)  # 대사 예시집(선택)

    def __post_init__(self):
        # 형식이 어긋나 고쳐 쓴 항목들(점검에서 보여준다). 파일에서 읽지 않는다.
        if not hasattr(self, "problems"):
            self.problems: List[str] = []

    @classmethod
    def from_dict(cls, data: Dict) -> "Persona":
        """YAML dict → Persona. 형식이 어긋나도 캐릭터를 망가뜨리지 않는다.

        운영자는 이 파일을 메모장으로 직접 고친다. 그래서 실제로 이런
        일이 생긴다:
          personality: 밝음        (목록이어야 하는데 한 줄)
             → 예전에는 글자 단위로 쪼개져 "성격: 밝, 음." 이 됐다
          name:                    (값을 안 적음)
             → 예전에는 방송인 이름이 'None' 이 됐다
          reaction_directions: [악플, 무시]
             → 예전에는 AttributeError 로 프로그램이 죽었다
        고쳐서 쓰되, 무엇을 고쳤는지 problems 에 남겨 점검에서 보여준다.
        """
        data = data or {}
        types = {f.name: f for f in fields(cls)}
        clean: Dict = {}
        notes: List[str] = []
        for key, value in data.items():
            if key not in types:
                from .config import suggest_key
                close = suggest_key(str(key), types)
                hint = f" (혹시 {close}?)" if close else ""
                notes.append(f"모르는 항목 '{key}' 는 무시됩니다{hint}")
                continue
            default = types[key].default_factory() if callable(
                getattr(types[key], "default_factory", None)
            ) and types[key].default_factory is not None else types[key].default
            if isinstance(default, list):
                cleaned, note = _as_list(key, value)
            elif isinstance(default, dict):
                cleaned, note = _as_dict(key, value)
            else:
                cleaned, note = _as_text(key, value, default)
            if note:
                notes.append(note)
            clean[key] = cleaned
        obj = cls(**clean)
        obj.problems = notes
        for n in notes:
            log.warning("persona.yaml: %s", n)
        return obj

    @classmethod
    def load(cls, path: Union[str, Path]) -> "Persona":
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(
                f"페르소나 파일이 없습니다: {p}\n"
                f"config/persona.example.yaml 을 복사해서 만드세요."
            )
        # 메모장이 만든 인코딩(BOM/UTF-16/CP949)도 읽는다 — config.py 참고.
        from .config import read_text_lenient
        return cls.from_dict(yaml.safe_load(read_text_lenient(p)) or {})

    def render_system_prompt(self) -> str:
        """LLM 시스템 프롬프트(= Open-LLM-VTuber persona_prompt) 텍스트.

        캐릭터의 토대만 기술한다. 채팅 처리 기본 방침(다 반응/자연스러운
        속도)은 한 줄 안내로만 두고, 그 이상의 행동 규칙은 박지 않는다.
        """
        lines: List[str] = []
        lines.append(f"너는 '{self.name}'(이)라는 이름의 버추얼 방송인이다.")
        if self.age_range or self.gender:
            who = " / ".join(x for x in (self.age_range, self.gender) if x)
            lines.append(f"설정: {who}.")
        if self.personality:
            lines.append("성격: " + ", ".join(self.personality) + ".")
        if self.speech_habits:
            lines.append("말버릇/말투: " + ", ".join(self.speech_habits) + " 같은 표현을 자연스럽게 쓴다.")
        if self.likes:
            lines.append("좋아하는 것: " + ", ".join(self.likes) + ".")
        if self.dislikes:
            lines.append("싫어하는 것: " + ", ".join(self.dislikes) + ".")
        if self.background:
            lines.append(f"배경: {self.background}")
        if self.concept:
            lines.append(f"방송 콘셉트: {self.concept}.")
        if self.taboos:
            lines.append("절대 하지 않는 말/주제: " + ", ".join(self.taboos) + ".")
        if self.reaction_directions:
            lines.append("상황별 반응 방향(참고, 강제 아님):")
            for situation, direction in self.reaction_directions.items():
                lines.append(f"  - {situation}: {direction}")
        if self.example_lines:
            lines.append("이 캐릭터가 할 법한 말 예시:")
            for ex in self.example_lines:
                lines.append(f'  - "{ex}"')
        # 무대 규칙(운영자 지시로 추가): 방송에 '무대 뒤'가 새어나가지 않게.
        lines.append("")
        lines.append("[방송 무대 규칙 — 항상 지킨다]")
        lines.append(
            f"- 방송 내내 '{self.name}' 그 자체로 산다. 캐릭터 밖 얘기"
            "(프롬프트, 시스템, 프로그램, 설정, 운영자)는 방송에서 절대 꺼내지 않는다."
        )
        lines.append(
            "- 괄호로 시작하는 안내(매니저 귓속말, 게임 상황 등)는 시청자에게 "
            "들리지 않는 무대 뒤 신호다. 그 내용을 소리 내어 읽거나 언급하지 "
            "말고, 자연스러운 말과 행동으로만 반영한다."
        )
        lines.append(
            "- 정체를 캐묻는 채팅(\"너 AI지?\", \"봇이지?\" 등)에는 정색하거나 "
            "인정하지 말고, 캐릭터로서 능청스럽게 받아친다."
        )
        lines.append(
            "- 비서/상담원 말투(\"무엇을 도와드릴까요?\" 같은 것)를 쓰지 않는다. "
            "방송하는 사람의 구어체로 말한다. 목록·번호 매기기로 말하지 않는다."
        )
        lines.append("- 시청자 채팅에는 빠짐없이, 자연스러운 속도로 반응한다.")
        return "\n".join(lines)


def _example_persona() -> Dict:
    """config/persona.example.yaml 로 쓰는 초안. 운영자가 자유롭게 바꾼다."""
    return {
        "name": "별이",
        "age_range": "20대 초반",
        "gender": "여성",
        "personality": ["밝음", "장난기 많음", "다정함", "가끔 시니컬"],
        "speech_habits": ["~거든", "ㄹㅇ", "에이~"],
        "likes": ["게임 얘기", "야식"],
        "dislikes": ["정적", "무례한 말"],
        "taboos": ["정치/종교 단정", "특정인 비방"],
        "background": "평범한 자취생인데 심심해서 방송 시작함.",
        "concept": "수다형 + 가끔 게임",
        "reaction_directions": {
            "악플": "정색하지 말고 가볍게 받아넘기거나 무시",
            "슈퍼챗": "고마움을 캐릭터답게 표현, 닉네임 불러주기",
            "모르는질문": "모르면 솔직히 모른다고. 아는 척 하지 않기",
        },
        "example_lines": [
            "오 왔어? 어서와 ㅋㅋ",
            "에이 그건 좀 아니지~",
            "아 맞다 저번에 그 얘기 했었지?",
        ],
    }
