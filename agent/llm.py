"""LLM: a única peça que fala com o modelo, via gateway LiteLLM (API compatível com a da OpenAI).
Trocar de provedor = mexer só aqui."""
import os

from openai import OpenAI

REQUIRED_ENV = ("LITELLM_BASE_URL", "LITELLM_API_KEY", "LITELLM_MODEL")


class LLMConfigError(RuntimeError):
    pass


class LLM:
    def __init__(self, timeout: float = 120.0):
        missing = [k for k in REQUIRED_ENV if not os.environ.get(k)]
        if missing:
            raise LLMConfigError(f"Defina no .env: {', '.join(missing)}")
        base_url = os.environ["LITELLM_BASE_URL"]
        if not base_url.startswith(("http://", "https://")):
            base_url = "https://" + base_url
        self.client = OpenAI(base_url=base_url, api_key=os.environ["LITELLM_API_KEY"], timeout=timeout)
        self.model = os.environ["LITELLM_MODEL"]

    def chat(self, messages: list, tools: list):
        """Uma chamada ao modelo. Retorna a mensagem do assistente (texto e/ou tool_calls)."""
        kwargs = {"model": self.model, "messages": messages}
        if tools:
            kwargs["tools"] = tools
        return self.client.chat.completions.create(**kwargs).choices[0].message
