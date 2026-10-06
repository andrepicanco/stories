"""Configuração da ferramenta: settings.json (sem segredos) + .env (segredos)."""
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SETTINGS_PATH = ROOT / "config" / "settings.json"
LOCAL_PATH = ROOT / "config" / "settings.local.json"
ENV_PATH = ROOT / ".env"

SECRET_KEYS = ("AZDO_PAT", "AZURE_OPENAI_API_KEY")


def load_dotenv(path: Path = ENV_PATH) -> None:
    """Lê o .env. Ele vence variáveis de ambiente do sistema com o mesmo nome (que podem estar
    desatualizadas, ex.: um AZDO_PAT antigo definido no Windows) para a ferramenta ser previsível."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ[key.strip()] = value.strip().strip('"').strip("'")


def _merge(base: dict, override: dict) -> dict:
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _merge(base[key], value)
        else:
            base[key] = value
    return base


def load_settings() -> dict:
    data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    if LOCAL_PATH.exists():
        _merge(data, json.loads(LOCAL_PATH.read_text(encoding="utf-8")))
    return data


def save_settings(patch: dict) -> dict:
    """Grava só o que o usuário alterou em settings.local.json (ignorado pelo git)."""
    current = json.loads(LOCAL_PATH.read_text(encoding="utf-8")) if LOCAL_PATH.exists() else {}
    _merge(current, patch)
    LOCAL_PATH.write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8")
    return load_settings()


def secrets_status() -> dict:
    """Informa quais segredos existem, sem nunca expor o valor."""
    return {key: bool(os.environ.get(key)) for key in SECRET_KEYS}
