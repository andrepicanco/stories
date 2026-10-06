"""Execuções do agente em segundo plano, com andamento consultável (as tools chamadas até agora).

Uma geração pode levar de segundos a minutos. O front inicia o job, consulta o andamento a cada instante
e recebe o resultado ao final, sem manter uma requisição HTTP aberta."""
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Callable

JOB_TTL_SECONDS = 3600


@dataclass
class Job:
    id: str
    status: str = "running"                       # running | done | error
    steps: list[dict] = field(default_factory=list)
    result: dict | None = None
    error: str = ""
    created_at: float = field(default_factory=time.time)

    def public(self) -> dict:
        return {"id": self.id, "status": self.status, "steps": list(self.steps),
                "result": self.result, "error": self.error}


class JobStore:
    def __init__(self):
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def start(self, work: Callable[[Callable[[dict], None]], dict]) -> Job:
        """Roda `work(on_step)` numa thread. `on_step(dict)` registra um passo do agente."""
        job = Job(id=uuid.uuid4().hex)
        with self._lock:
            self._purge()
            self._jobs[job.id] = job

        def runner():
            try:
                job.result = work(lambda step: job.steps.append(step))
                job.status = "done"
            except Exception as err:  # noqa: BLE001 - o erro vai para o usuário, não derruba a thread
                job.error = str(err) or type(err).__name__
                job.status = "error"

        threading.Thread(target=runner, name=f"job-{job.id[:6]}", daemon=True).start()
        return job

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def _purge(self) -> None:
        cutoff = time.time() - JOB_TTL_SECONDS
        for job_id in [j for j, job in self._jobs.items() if job.created_at < cutoff and job.status != "running"]:
            del self._jobs[job_id]


jobs = JobStore()
