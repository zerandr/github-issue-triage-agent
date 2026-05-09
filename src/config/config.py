import os
import logging

from typing import Any
from dotenv import load_dotenv


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)

load_dotenv()


class Singleton(type):
    _instance = None

    def __call__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__call__(*args, **kwargs)
        return cls._instance

    def reset(self):
        self._instance = None


class Config(metaclass=Singleton):
    def __init__(self) -> None:
        self.ollama_url = Config._get("OLLAMA_URL", "http://127.0.0.1:11434")
        self.ollama_model = Config._get("OLLAMA_MODEL", "qwen2.5:7b-instruct")
        self.github_api = "https://api.github.com"
        self.cache_path = "data/cache/triage_cache.sqlite"
        self.retriable_http = {408, 429, 500, 502, 503, 504}

    @staticmethod
    def _get(key: str, fallback: Any = None) -> Any:
        return os.environ.get(key.upper(), fallback)
