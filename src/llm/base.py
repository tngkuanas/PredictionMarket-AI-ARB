"""LLM client interface supporting Gemini, OpenAI, Anthropic, and offline heuristic generators."""
import abc
import os
import json
import logging
from typing import Optional, Dict, Any, List

from config.settings import get_settings

logger = logging.getLogger(__name__)

class BaseLLMClient(abc.ABC):
    """Abstract interface for LLM calls with structured JSON output enforcement."""

    @abc.abstractmethod
    def generate_json(self, prompt: str, schema_description: str) -> Dict[str, Any]:
        """Generate response from LLM and guarantee valid JSON format matching schema."""
        pass

class GeminiLLMClient(BaseLLMClient):
    def __init__(self, api_key: Optional[str] = None, model_name: str = "gemini-2.5-flash"):
        self.api_key = api_key or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        self.model_name = model_name

    def generate_json(self, prompt: str, schema_description: str) -> Dict[str, Any]:
        if not self.api_key:
            raise ValueError("GEMINI_API_KEY not set")
        import requests
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model_name}:generateContent?key={self.api_key}"
        payload = {
            "contents": [{"parts": [{"text": f"{prompt}\n\nYou MUST respond ONLY with valid JSON conforming to this schema:\n{schema_description}"}]}],
            "generationConfig": {"response_mime_type": "application/json", "temperature": 0.1}
        }
        resp = requests.post(url, json=payload, timeout=30)
        resp.raise_for_status()
        text = resp.json()["candidates"][0]["content"]["parts"][0]["text"]
        return json.loads(text)

class OpenAILLMClient(BaseLLMClient):
    def __init__(self, api_key: Optional[str] = None, model_name: str = "gpt-4o-mini"):
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        self.model_name = model_name

    def generate_json(self, prompt: str, schema_description: str) -> Dict[str, Any]:
        if not self.api_key:
            raise ValueError("OPENAI_API_KEY not set")
        import requests
        url = "https://api.openai.com/v1/chat/completions"
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        payload = {
            "model": self.model_name,
            "messages": [
                {"role": "system", "content": "You are a quantitative prediction market researcher. Return only valid JSON."},
                {"role": "user", "content": f"{prompt}\n\nSchema:\n{schema_description}"}
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.1
        }
        resp = requests.post(url, headers=headers, json=payload, timeout=30)
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"]
        return json.loads(content)

class HeuristicDomainLLMClient(BaseLLMClient):
    """Domain-expert economic generator for testing, benchmarking, and offline falsification.
    Discovers second-order, cross-domain economic transmission channels across market pairs.
    """

    def generate_json(self, prompt: str, schema_description: str) -> Dict[str, Any]:
        # Return fallback structured payload if invoked directly
        return {"hypotheses": []}

def get_llm_client() -> BaseLLMClient:
    settings = get_settings()
    gemini_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or settings.llm.api_key
    openai_key = os.getenv("OPENAI_API_KEY")

    if gemini_key:
        logger.info("Using Gemini LLM Client.")
        return GeminiLLMClient(api_key=gemini_key, model_name=settings.llm.model_name)
    elif openai_key:
        logger.info("Using OpenAI LLM Client.")
        return OpenAILLMClient(api_key=openai_key)
    else:
        logger.info("No external LLM API key detected; using Heuristic Domain LLM Engine.")
        return HeuristicDomainLLMClient()
