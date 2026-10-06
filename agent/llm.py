"""LLM: a única peça que fala com o Azure OpenAI. Trocar de provedor = mexer só aqui."""
import os

from openai import AzureOpenAI

REQUIRED_ENV = ("AZURE_OPENAI_ENDPOINT", "AZURE_OPENAI_API_KEY", "AZURE_OPENAI_DEPLOYMENT")


class LLMConfigError(RuntimeError):
    pass


class LLM:
    def __init__(self, timeout: float = 120.0):
        missing = [k for k in REQUIRED_ENV if not os.environ.get(k)]
        if missing:
            raise LLMConfigError(f"Defina no .env: {', '.join(missing)}")
        endpoint = os.environ["AZURE_OPENAI_ENDPOINT"]
        if not endpoint.startswith(("http://", "https://")):
            endpoint = "https://" + endpoint
        self.client = AzureOpenAI(
            azure_endpoint=endpoint,
            api_key=os.environ["AZURE_OPENAI_API_KEY"],
            api_version=os.environ.get("AZURE_OPENAI_API_VERSION", "2024-10-21"),
            timeout=timeout,
        )
        self.deployment = os.environ["AZURE_OPENAI_DEPLOYMENT"]

    def chat(self, messages: list, tools: list):
        """Uma chamada ao modelo. Retorna a mensagem do assistente (texto e/ou tool_calls)."""
        kwargs = {"model": self.deployment, "messages": messages}
        if tools:
            kwargs["tools"] = tools
        return self.client.chat.completions.create(**kwargs).choices[0].message
