"""공지 문구 생성용 LLM 클라이언트.

provider: openai | anthropic | gemini | dummy
- 키는 .env(secrets)에서 받는다.
- dummy 는 네트워크 없이 동작(available()=False) → composer 가 오프라인
  변주 풀로 대체한다. 테스트/키 없는 환경에서 안전.
모든 SDK 는 지연 import.
"""

import logging
from typing import Optional

from .config import LlmConfig, Secrets

log = logging.getLogger("aist.llm")


class LLMClient:
    def __init__(self, cfg: LlmConfig, secrets: Secrets):
        self.cfg = cfg
        self.secrets = secrets

    def available(self) -> bool:
        """키가 있고 실제 호출 가능한 제공자인지."""
        p = self.cfg.provider
        if p == "openai":
            return bool(self.secrets.openai_api_key or self.cfg.base_url)
        if p == "anthropic":
            return bool(self.secrets.anthropic_api_key)
        if p == "gemini":
            return bool(self.secrets.gemini_api_key)
        if p == "ollama":
            return True  # 로컬 서버. 죽어있으면 complete 실패 → composer 가 폴백
        return False  # dummy

    def complete(self, system: str, user: str) -> str:
        """system+user 프롬프트로 한 번 호출하고 텍스트를 반환."""
        p = self.cfg.provider
        if p == "openai":
            return self._openai(system, user)
        if p == "anthropic":
            return self._anthropic(system, user)
        if p == "gemini":
            return self._gemini(system, user)
        if p == "ollama":
            return self._ollama(system, user)
        raise RuntimeError("dummy provider 는 complete() 를 호출하지 않습니다.")

    def _openai(self, system: str, user: str) -> str:
        from openai import OpenAI  # 지연 import
        kwargs = {}
        if self.secrets.openai_api_key:
            kwargs["api_key"] = self.secrets.openai_api_key
        if self.cfg.base_url:
            kwargs["base_url"] = self.cfg.base_url
        client = OpenAI(**kwargs)
        resp = client.chat.completions.create(
            model=self.cfg.model,
            temperature=self.cfg.temperature,
            max_tokens=self.cfg.max_tokens,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        return (resp.choices[0].message.content or "").strip()

    def _anthropic(self, system: str, user: str) -> str:
        import anthropic  # 지연 import
        client = anthropic.Anthropic(api_key=self.secrets.anthropic_api_key)
        resp = client.messages.create(
            model=self.cfg.model,
            max_tokens=self.cfg.max_tokens,
            temperature=self.cfg.temperature,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return "".join(getattr(b, "text", "") for b in resp.content).strip()

    def _ollama(self, system: str, user: str) -> str:
        """로컬 Ollama — OpenAI 호환 엔드포인트(/v1) 사용. 키 불필요, 비용 0."""
        from openai import OpenAI  # 지연 import
        client = OpenAI(
            base_url=self.cfg.base_url or "http://127.0.0.1:11434/v1",
            api_key="ollama",  # SDK 가 빈 키를 거부해서 더미 값
        )
        resp = client.chat.completions.create(
            model=self.cfg.model,
            temperature=self.cfg.temperature,
            max_tokens=self.cfg.max_tokens,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        return (resp.choices[0].message.content or "").strip()

    def _gemini(self, system: str, user: str) -> str:
        import google.generativeai as genai  # 지연 import
        genai.configure(api_key=self.secrets.gemini_api_key)
        model = genai.GenerativeModel(self.cfg.model, system_instruction=system)
        resp = model.generate_content(user)
        return (resp.text or "").strip()
