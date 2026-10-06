"""Cliente HTTP "educado" para leituras em lote no Azure DevOps (ingestão da ontologia).

Evita throttling e alertas de uso anômalo do PAT: requisições SEQUENCIAIS com intervalo mínimo, User-Agent
próprio, respeito a Retry-After e aos cabeçalhos X-RateLimit-*, recuo exponencial em 429/503 e PARADA
imediata em 401/403 (sem insistir). Nunca loga conteúdo, só contagens e códigos."""
import json
import time
import urllib.error
import urllib.request

from .azure_client import AzureError, _auth_header

USER_AGENT = "stories/2.0 (ontology-ingest)"
MIN_INTERVAL = 0.5          # segundos entre requisições
MAX_RETRIES = 4
MAX_WAIT = 60.0
CHUNK = 1024 * 1024


class PoliteStop(AzureError):
    """A ingestão deve parar (autenticação negada, limite persistente ou download grande demais)."""


class PoliteClient:
    def __init__(self, min_interval: float = MIN_INTERVAL, max_retries: int = MAX_RETRIES,
                 sleep=time.sleep, clock=time.monotonic):
        self.min_interval = min_interval
        self.max_retries = max_retries
        self._sleep = sleep
        self._clock = clock
        self._last = None
        self.requests = 0
        self.throttled = 0

    def _pace(self) -> None:
        if self._last is not None:
            wait = self.min_interval - (self._clock() - self._last)
            if wait > 0:
                self._sleep(wait)

    def get(self, url: str, accept: str = "application/json", max_bytes: int | None = None) -> tuple[bytes, dict]:
        return self.request("GET", url, None, accept, max_bytes)

    def post_json(self, url: str, body: dict):
        """POST de uma consulta (ex.: WIQL) com as mesmas regras; devolve o JSON da resposta."""
        data, _ = self.request("POST", url, body)
        return json.loads(data.decode("utf-8"))

    def request(self, method: str, url: str, body: dict | None, accept: str = "application/json",
                max_bytes: int | None = None) -> tuple[bytes, dict]:
        """Requisição com as regras acima. `max_bytes` aborta downloads maiores que o teto (sem baixar o resto)."""
        attempt = 0
        payload = json.dumps(body).encode("utf-8") if body is not None else None
        while True:
            self._pace()
            self.requests += 1
            headers = {"Authorization": _auth_header(), "Accept": accept, "User-Agent": USER_AGENT}
            if payload is not None:
                headers["Content-Type"] = "application/json"
            request = urllib.request.Request(url, data=payload, headers=headers, method=method)
            try:
                with urllib.request.urlopen(request, timeout=120) as response:
                    headers = {k.lower(): v for k, v in response.headers.items()}
                    declared = int(headers.get("content-length") or 0)
                    if max_bytes and declared > max_bytes:
                        raise PoliteStop(f"download de {declared // 1_000_000} MB acima do limite de {max_bytes // 1_000_000} MB", 413)
                    data = bytearray()
                    while chunk := response.read(CHUNK):
                        data.extend(chunk)
                        if max_bytes and len(data) > max_bytes:
                            raise PoliteStop(f"download acima do limite de {max_bytes // 1_000_000} MB", 413)
                self._last = self._clock()
                self._respect_rate_headers(headers)
                return bytes(data), headers
            except urllib.error.HTTPError as err:
                self._last = self._clock()
                if err.code in (401, 403):
                    raise PoliteStop("PAT inválido, expirado ou sem permissão para esta leitura.", err.code) from err
                if err.code in (429, 503):
                    self.throttled += 1
                    attempt += 1
                    if attempt > self.max_retries:
                        raise PoliteStop("O Azure DevOps continua limitando as requisições; tente mais tarde.", err.code) from err
                    self._sleep(self._retry_wait(err.headers.get("Retry-After"), attempt))
                    continue
                raise AzureError(f"Azure DevOps respondeu {err.code}", err.code) from err
            except urllib.error.URLError as err:
                raise AzureError(f"Não foi possível conectar ao Azure DevOps: {err.reason}") from err

    def get_json(self, url: str):
        data, _ = self.get(url)
        return json.loads(data.decode("utf-8"))

    @staticmethod
    def _retry_wait(retry_after, attempt: int) -> float:
        try:
            return min(float(retry_after), MAX_WAIT)
        except (TypeError, ValueError):
            return min(2.0 ** attempt, MAX_WAIT)

    def _respect_rate_headers(self, headers: dict) -> None:
        """O Azure DevOps pede pausa antes de bloquear: X-RateLimit-Delay (s) e saldo baixo até o Reset."""
        try:
            delay = float(headers.get("x-ratelimit-delay") or 0)
        except ValueError:
            delay = 0
        try:
            remaining = float(headers.get("x-ratelimit-remaining")) if headers.get("x-ratelimit-remaining") else None
            reset = float(headers.get("x-ratelimit-reset") or 0)
        except ValueError:
            remaining, reset = None, 0
        if remaining is not None and remaining < 5 and reset:
            delay = max(delay, reset - time.time())
        if delay > 0:
            self.throttled += 1
            self._sleep(min(delay, MAX_WAIT))
