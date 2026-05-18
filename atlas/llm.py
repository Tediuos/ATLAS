"""Wrapper LLM qui parle indifféremment à Groq ou Ollama."""
import os
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()


def get_llm_client():
    """Retourne un tuple (client, model_name) selon LLM_PROVIDER dans .env."""
    provider = os.getenv("LLM_PROVIDER", "groq").lower()

    if provider == "groq":
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            raise RuntimeError("GROQ_API_KEY manquante dans .env")
        client = OpenAI(
            api_key=api_key,
            base_url="https://api.groq.com/openai/v1",
        )
        model = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
        return client, model

    if provider == "ollama":
        client = OpenAI(
            api_key="ollama",  # requis par le SDK mais ignoré par Ollama
            base_url="http://localhost:11434/v1",
        )
        model = os.getenv("OLLAMA_MODEL", "qwen2.5:7b")
        return client, model

    raise ValueError(f"LLM_PROVIDER inconnu: {provider}")