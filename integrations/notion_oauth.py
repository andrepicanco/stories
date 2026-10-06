"""OAuth do MCP remoto do Notion (descoberta + registro dinâmico de cliente + PKCE) com refresh automático.

Adaptado da v1, sem qualquer dependência de CLI externa: a URL do servidor vem das configurações
e os tokens ficam em storage/notion-auth.json (ignorado pelo git)."""
import base64
import hashlib
import json
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

REFRESH_MARGIN_SECONDS = 120
PENDING_TTL_SECONDS = 15 * 60
CLIENT_NAME = "Stories"


class NotionAuthError(RuntimeError):
    pass


class NotAuthorized(NotionAuthError):
    """Sem token válido: o usuário precisa (re)conectar o Notion."""


def _http(url: str, *, payload: dict | None = None, form: dict | None = None) -> dict:
    headers = {"Accept": "application/json", "User-Agent": "stories/2.0"}
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    elif form is not None:
        data = urllib.parse.urlencode(form).encode("utf-8")
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    request = urllib.request.Request(url, data=data, headers=headers, method="POST" if data is not None else "GET")
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            parsed = json.loads(response.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as err:
        detail = err.read().decode("utf-8", errors="replace")[:300] if err.fp else str(err)
        raise NotionAuthError(f"Notion respondeu HTTP {err.code}: {detail}") from err
    except urllib.error.URLError as err:
        raise NotionAuthError(f"Falha de rede ao falar com o Notion: {err.reason}") from err
    except json.JSONDecodeError as err:
        raise NotionAuthError("Resposta inválida do Notion (não é JSON).") from err
    if not isinstance(parsed, dict):
        raise NotionAuthError("Resposta inesperada do Notion.")
    return parsed


def _challenge(verifier: str) -> str:
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")


class NotionOAuth:
    def __init__(self, auth_file: Path, server_url: str):
        self.auth_file = Path(auth_file)
        self.server_url = server_url.rstrip("/")
        self._lock = threading.Lock()

    # ---------- estado ----------
    def _load(self) -> dict:
        try:
            data = json.loads(self.auth_file.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def _save(self, data: dict) -> None:
        self.auth_file.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.auth_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        tmp.replace(self.auth_file)

    def status(self) -> dict:
        data = self._load()
        tokens = data.get("tokens") or {}
        expires_at = int(tokens.get("expires_at") or 0)
        return {
            "has_token": bool(tokens.get("access_token")),
            "has_refresh_token": bool(tokens.get("refresh_token")),
            "expired": bool(expires_at and expires_at <= time.time()),
            "server_matches": data.get("server_url") == self.server_url,
        }

    def is_connected(self) -> bool:
        s = self.status()
        return s["has_token"] and s["server_matches"] and (not s["expired"] or s["has_refresh_token"])

    # ---------- fluxo de autorização ----------
    def begin(self, redirect_uri: str) -> str:
        """Devolve a URL de autorização do Notion. Registra o cliente se for novo ou se o redirect mudou."""
        meta = self._discover()
        data = self._load()
        client = data.get("client") or {}
        if (data.get("server_url") != self.server_url or not client.get("client_id")
                or data.get("redirect_uri") != redirect_uri):
            registered = _http(meta["registration_endpoint"], payload={
                "client_name": CLIENT_NAME,
                "redirect_uris": [redirect_uri],
                "grant_types": ["authorization_code", "refresh_token"],
                "response_types": ["code"],
                "token_endpoint_auth_method": "none",
            })
            if not registered.get("client_id"):
                raise NotionAuthError("O Notion não devolveu client_id no registro do cliente.")
            client = {"client_id": registered["client_id"], "client_secret": registered.get("client_secret", "")}
            data = {"tokens": {}}   # cliente novo invalida tokens antigos

        verifier = secrets.token_urlsafe(64)
        state = secrets.token_urlsafe(32)
        data.update({
            "server_url": self.server_url, "redirect_uri": redirect_uri, "oauth": meta, "client": client,
            "pending": {"state": state, "verifier": verifier, "created_at": int(time.time())},
        })
        self._save(data)
        query = urllib.parse.urlencode({
            "response_type": "code", "client_id": client["client_id"], "redirect_uri": redirect_uri,
            "state": state, "code_challenge": _challenge(verifier), "code_challenge_method": "S256",
            "prompt": "consent",
        })
        return f"{meta['authorization_endpoint']}?{query}"

    def complete(self, code: str, state: str) -> None:
        data = self._load()
        pending = data.get("pending") or {}
        if not pending or state != pending.get("state"):
            raise NotionAuthError("Estado OAuth inválido. Clique em conectar novamente.")
        if time.time() - pending.get("created_at", 0) > PENDING_TTL_SECONDS:
            raise NotionAuthError("A autorização expirou. Clique em conectar novamente.")
        response = _http(data["oauth"]["token_endpoint"], form={
            "grant_type": "authorization_code", "code": code, "client_id": data["client"]["client_id"],
            "redirect_uri": data["redirect_uri"], "code_verifier": pending["verifier"],
            **({"client_secret": data["client"]["client_secret"]} if data["client"].get("client_secret") else {}),
        })
        data["tokens"] = self._tokens_from(response, previous_refresh="")
        data.pop("pending", None)
        self._save(data)

    # ---------- token para uso ----------
    def access_token(self) -> str:
        """Token válido; renova com o refresh token quando está para expirar."""
        with self._lock:
            data = self._load()
            tokens = data.get("tokens") or {}
            if not tokens.get("access_token") or data.get("server_url") != self.server_url:
                raise NotAuthorized("Notion não conectado.")
            expires_at = int(tokens.get("expires_at") or 0)
            if expires_at and expires_at - REFRESH_MARGIN_SECONDS <= time.time():
                if not tokens.get("refresh_token"):
                    raise NotAuthorized("Token do Notion expirou. Conecte novamente.")
                try:
                    response = _http(data["oauth"]["token_endpoint"], form={
                        "grant_type": "refresh_token", "refresh_token": tokens["refresh_token"],
                        "client_id": data["client"]["client_id"],
                        **({"client_secret": data["client"]["client_secret"]} if data["client"].get("client_secret") else {}),
                    })
                except NotionAuthError as err:
                    raise NotAuthorized(f"Não foi possível renovar o token do Notion ({err}). Conecte novamente.") from err
                data["tokens"] = tokens = self._tokens_from(response, previous_refresh=tokens["refresh_token"])
                self._save(data)
            return tokens["access_token"]

    @staticmethod
    def _tokens_from(response: dict, previous_refresh: str) -> dict:
        access = str(response.get("access_token", "")).strip()
        if not access:
            raise NotionAuthError("O Notion não devolveu access_token.")
        try:
            expires_in = int(response.get("expires_in") or 0)
        except (TypeError, ValueError):
            expires_in = 0
        return {
            "access_token": access,
            "refresh_token": str(response.get("refresh_token") or previous_refresh),
            "expires_at": int(time.time()) + expires_in if expires_in > 0 else 0,
        }

    def _discover(self) -> dict:
        parsed = urllib.parse.urlsplit(self.server_url)
        if not parsed.scheme or not parsed.netloc:
            raise NotionAuthError("URL do servidor Notion MCP inválida.")
        origin = f"{parsed.scheme}://{parsed.netloc}"
        resource = _http(f"{origin}/.well-known/oauth-protected-resource")
        servers = resource.get("authorization_servers") or []
        if not servers:
            raise NotionAuthError("O Notion MCP não informou o servidor de autorização.")
        meta = _http(f"{str(servers[0]).rstrip('/')}/.well-known/oauth-authorization-server")
        for key in ("authorization_endpoint", "token_endpoint", "registration_endpoint"):
            if not meta.get(key):
                raise NotionAuthError(f"Metadados OAuth do Notion sem '{key}'.")
        return {k: meta[k] for k in ("issuer", "authorization_endpoint", "token_endpoint", "registration_endpoint") if k in meta}
