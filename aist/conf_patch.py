"""주석을 지우지 않고 YAML 값 하나만 바꾼다.

코어(Open-LLM-VTuber)의 conf.yaml 은 설명 주석이 빽빽한 파일이다.
운영자가 여기서 LLM 키·TTS 경로 같은 걸 직접 채워야 하는데, 우리가
yaml.safe_load → safe_dump 로 다시 쓰면 주석이 전부 사라진다(실제로
conf.korean.yaml 이 그렇게 만들어져 주석 135줄이 통째로 없었다).

그래서 파일을 텍스트로 다루고 해당 키의 값 부분만 갈아끼운다.
바꾼 결과는 반드시 YAML 로 다시 읽어서
  1) 파싱이 되는지
  2) 목표 값이 정확히 들어갔는지
  3) 나머지 값이 하나도 안 변했는지
를 확인한다. 하나라도 어긋나면 ConfPatchError 를 올린다 — 호출자는
예전 방식(safe_dump)으로 물러설 수 있다. 코어 설정을 깨뜨리는 것보다
주석을 잃는 게 낫다.
"""

from typing import List, Optional, Sequence, Tuple

import yaml


class ConfPatchError(Exception):
    pass


def _indent_of(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _is_key_line(line: str) -> bool:
    s = line.strip()
    if not s or s.startswith("#") or s.startswith("-"):
        return False
    key, sep, _ = s.partition(":")
    return bool(sep) and key == key.strip() and " " not in key.strip()


def _key_of(line: str) -> str:
    return line.strip().partition(":")[0].strip()


def find_key(lines: Sequence[str], path: Sequence[str]) -> Optional[Tuple[int, int]]:
    """path(예: ["character_config", "persona_prompt"])의 (줄번호, 들여쓰기)."""
    depth = 0
    parent_indent = -1
    for i, line in enumerate(lines):
        if not _is_key_line(line):
            continue
        indent = _indent_of(line)
        if depth > 0 and indent <= parent_indent:
            # 부모 블록을 벗어났다 — 처음부터 다시 찾는다
            depth = 0
            parent_indent = -1
        if _key_of(line) != path[depth]:
            continue
        if depth == len(path) - 1:
            return i, indent
        depth += 1
        parent_indent = indent
    return None


def _value_span(lines: Sequence[str], start: int, indent: int) -> int:
    """값이 차지하는 마지막 줄(포함) 번호."""
    end = start
    j = start + 1
    last_nonblank = start
    while j < len(lines):
        line = lines[j]
        if line.strip() == "":
            j += 1
            continue
        if _indent_of(line) > indent:
            last_nonblank = j
            j += 1
            continue
        break
    return max(end, last_nonblank)


def _trailing_comment(line: str) -> str:
    """값 뒤에 붙은 설명 주석(있으면). 운영자에게는 이 설명이 중요하다."""
    body = line.split(":", 1)[1] if ":" in line else ""
    in_s = in_d = False
    for i, ch in enumerate(body):
        if ch == "'" and not in_d:
            in_s = not in_s
        elif ch == '"' and not in_s:
            in_d = not in_d
        elif ch == "#" and not in_s and not in_d:
            return body[i:].rstrip()
    return ""


def _render(key: str, value: str, indent: int, comment: str = "") -> List[str]:
    pad = " " * indent
    if "\n" in value:
        # |- : 블록 끝의 줄바꿈을 붙이지 않는다(값이 정확히 일치해야 검증을 통과)
        out = [f"{pad}{key}: |-"]
        for ln in value.split("\n"):
            out.append(f"{pad}  {ln}" if ln else "")
        return out
    # safe_dump 에 스칼라만 주면 문서 끝 표시(...)가 붙어 파일이 깨진다.
    # 키와 함께 덤프해서 그 한 줄을 그대로 쓴다.
    dumped = yaml.safe_dump({key: value}, allow_unicode=True, width=10 ** 6,
                            default_flow_style=False).rstrip("\n")
    lines = [pad + ln for ln in dumped.split("\n")]
    if comment and len(lines) == 1:
        lines[0] = f"{lines[0]} {comment}"
    return lines


def _flat(d, p="") -> dict:
    out = {}
    if isinstance(d, dict):
        for k, v in d.items():
            if isinstance(v, dict):
                out.update(_flat(v, f"{p}{k}."))
            else:
                out[f"{p}{k}"] = v
    return out


def set_value(text: str, path: Sequence[str], value: str) -> str:
    """주석을 유지한 채 path 의 값을 value 로 바꾼다."""
    lines = text.split("\n")
    found = find_key(lines, path)
    if found is None:
        raise ConfPatchError(f"키를 찾지 못했습니다: {'.'.join(path)}")
    i, indent = found
    end = _value_span(lines, i, indent)
    comment = _trailing_comment(lines[i]) if end == i else ""
    new_lines = (lines[:i] + _render(path[-1], value, indent, comment)
                 + lines[end + 1:])
    new_text = "\n".join(new_lines)

    # --- 검증: 깨뜨리느니 물러선다 ---
    try:
        before = _flat(yaml.safe_load(text) or {})
        after = _flat(yaml.safe_load(new_text) or {})
    except yaml.YAMLError as e:
        raise ConfPatchError(f"바꾼 결과가 YAML 로 안 읽힙니다: {e}") from e
    dotted = ".".join(path)
    if after.get(dotted) != value:
        raise ConfPatchError(
            f"{dotted} 값이 의도대로 안 들어갔습니다: {after.get(dotted)!r}")
    changed = {k for k in set(before) | set(after)
               if before.get(k) != after.get(k)}
    extra = changed - {dotted}
    if extra:   # 원래 값과 같았으면 changed 가 비는 것도 정상
        raise ConfPatchError(f"다른 값까지 바뀌었습니다: {sorted(extra)}")
    return new_text
