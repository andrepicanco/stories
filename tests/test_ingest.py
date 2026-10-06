import io
import json
import tempfile
import unittest
import urllib.error
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from agent.knowledge import ingest
from agent.knowledge.secrets import find_secrets
from agent.knowledge.store import OntologyStore, dump_note, parse_frontmatter
from integrations import azure_client as az
from integrations import polite
from integrations.polite import PoliteClient, PoliteStop
from integrations.wiki_url import parse_wiki_url

WIKI_URL = ("https://dev.azure.com/Org/Proj/_wiki/wikis/W.wiki/10/Raiz")


# ---------- cliente educado ----------

class FakeResponse:
    def __init__(self, body=b"{}", headers=None):
        self._data, self.headers = io.BytesIO(body), headers or {}

    def read(self, n=-1):
        return self._data.read(n)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def http_error(code, headers=None):
    return urllib.error.HTTPError("http://x", code, "err", headers or {}, io.BytesIO(b"{}"))


class PoliteClientTests(unittest.TestCase):
    def setUp(self):
        self.sleeps = []
        self.now = [100.0]
        self.client = PoliteClient(min_interval=0.5, max_retries=2, sleep=self.sleeps.append, clock=lambda: self.now[0])
        patcher = mock.patch.object(polite, "_auth_header", return_value="Basic x")
        patcher.start()
        self.addCleanup(patcher.stop)

    def get(self, side_effect):
        with mock.patch("urllib.request.urlopen", side_effect=side_effect) as m:
            return self.client.get("http://x"), m

    def test_429_respeita_retry_after_e_tenta_de_novo(self):
        (data, _), m = self.get([http_error(429, {"Retry-After": "7"}), FakeResponse(b"ok")])
        self.assertEqual(data, b"ok")
        self.assertIn(7.0, self.sleeps)
        self.assertEqual(self.client.requests, 2)

    def test_429_sem_retry_after_recua_exponencialmente(self):
        self.get([http_error(503), http_error(503), FakeResponse()])
        self.assertEqual([s for s in self.sleeps if s >= 1], [2.0, 4.0])

    def test_para_apos_o_limite_de_tentativas(self):
        with mock.patch("urllib.request.urlopen", side_effect=[http_error(429)] * 5):
            with self.assertRaises(PoliteStop):
                self.client.get("http://x")
        self.assertEqual(self.client.requests, 3)    # 1 + 2 retentativas, sem insistir

    def test_401_e_403_param_na_hora_sem_retentativa(self):
        for code in (401, 403):
            client = PoliteClient(sleep=self.sleeps.append)
            with mock.patch("urllib.request.urlopen", side_effect=[http_error(code), FakeResponse()]):
                with self.assertRaises(PoliteStop) as ctx:
                    client.get("http://x")
            self.assertEqual(ctx.exception.status, code)
            self.assertEqual(client.requests, 1)

    def test_intervalo_minimo_entre_requisicoes(self):
        with mock.patch("urllib.request.urlopen", side_effect=[FakeResponse(), FakeResponse()]):
            self.client.get("http://x")
            self.now[0] += 0.1
            self.client.get("http://x")
        self.assertAlmostEqual(self.sleeps[-1], 0.4, places=5)

    def test_respeita_x_ratelimit_delay(self):
        self.get([FakeResponse(headers={"X-RateLimit-Delay": "3.5"})])
        self.assertIn(3.5, self.sleeps)

    def test_download_acima_do_teto_aborta_sem_baixar(self):
        response = FakeResponse(b"x" * 10, headers={"Content-Length": "999999999"})
        with mock.patch("urllib.request.urlopen", return_value=response):
            with self.assertRaises(PoliteStop) as ctx:
                self.client.get("http://x", max_bytes=1_000_000)
        self.assertEqual(ctx.exception.status, 413)

    def test_requisicoes_sao_sequenciais_e_identificadas(self):
        with mock.patch("urllib.request.urlopen", return_value=FakeResponse()) as m:
            self.client.get("http://x")
        sent = m.call_args[0][0]
        self.assertEqual(sent.get_header("User-agent"), polite.USER_AGENT)


# ---------- segredos ----------

class SecretsTests(unittest.TestCase):
    def test_detecta_tipos_sem_devolver_o_trecho(self):
        text = "senha: Abc12345xyz e Bearer abcdefghijklmnopqrstuvwxyz123 e postgres://user:pass@host/db"
        kinds = find_secrets(text)
        self.assertIn("senha/segredo atribuído", kinds)
        self.assertIn("token Bearer", kinds)
        self.assertIn("credencial em URL", kinds)
        self.assertNotIn("Abc12345xyz", " ".join(kinds))

    def test_texto_comum_nao_dispara(self):
        self.assertEqual(find_secrets("A renegociação gera um acordo. O token expira em uma hora."), [])


# ---------- caminhos e leitura da wiki ----------

class WikiPathTests(unittest.TestCase):
    def test_git_path_e_inverso(self):
        page = "/Bemol Serviços Financeiros/Estrutura de Times - BSF/Time de Desenvolvimento/💜 Violet (Cobrança)"
        git = ingest.git_path(page)
        self.assertEqual(git, "/Bemol-Serviços-Financeiros/Estrutura-de-Times-%2D-BSF/Time-de-Desenvolvimento/💜-Violet-(Cobrança)")
        self.assertEqual("/" + ingest.page_from_git(git.lstrip("/")), page)
        self.assertEqual(ingest.page_from_git("Gestao/Rito-daily.md"), "Gestao/Rito daily")

    def test_fetch_wiki_le_o_zip_da_subarvore(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("Raiz/Governança-Ágil.md", "# Governança\nTexto " * 30)
            z.writestr("Raiz/Sub/Fluxo-do-Board.md", "Fluxo " * 60)
            z.writestr("Raiz/.attachments/img.md", "ignorado")
            z.writestr("Raiz/imagem.png", "ignorado")
        zip_bytes = buf.getvalue()

        class FakeClient:
            requests = 0

            def get_json(self, url):
                if "/commits" in url:
                    return {"value": [{"commitId": "abc123"}]}
                return {"repositoryId": "repo-1"}

            def get(self, url, accept="application/json", max_bytes=None):
                if "$format=zip" in url:
                    return zip_bytes, {}
                raise az.AzureError("404", 404)     # a página raiz (arquivo ao lado) não existe

        wiki = parse_wiki_url(WIKI_URL)
        with mock.patch.object(az, "wiki_root_path", return_value="/Raiz"), \
             mock.patch.dict(ingest._FETCH_CACHE, clear=True), \
             mock.patch.object(ingest, "load_state", return_value={}):
            result = ingest.fetch_wiki(wiki, FakeClient(), [], 150)
        self.assertEqual(result["via"], "zip")
        self.assertEqual(result["commit"], "abc123")
        self.assertEqual(set(result["pages"]), {"Governança Ágil", "Sub/Fluxo do Board"})

    def test_zip_com_a_pasta_raiz_como_diretorio_de_topo(self):
        """Formato real do Azure DevOps: a subárvore vem como '<pasta da raiz>/...'."""
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("💜-Violet-(Cobrança)/Governança-Ágil.md", "Texto " * 60)
            z.writestr("💜-Violet-(Cobrança)/Gestao/Visao-atual.md", "Texto " * 60)
        zip_bytes = buf.getvalue()

        class FakeClient:
            requests = 0

            def get_json(self, url):
                return {"value": [{"commitId": "c9"}]} if "/commits" in url else {"repositoryId": "r"}

            def get(self, url, accept="application/json", max_bytes=None):
                if "$format=zip" in url:
                    return zip_bytes, {}
                raise az.AzureError("404", 404)

        wiki = parse_wiki_url(WIKI_URL)
        with mock.patch.object(az, "wiki_root_path", return_value="/Estrutura de Times - BSF/Time/💜 Violet (Cobrança)"), \
             mock.patch.dict(ingest._FETCH_CACHE, clear=True), \
             mock.patch.object(ingest, "load_state", return_value={}):
            result = ingest.fetch_wiki(wiki, FakeClient(), [], 150)
        self.assertEqual(set(result["pages"]), {"Governança Ágil", "Gestao/Visao atual"})

    def test_sem_mudanca_no_commit_nao_le_conteudo(self):
        class FakeClient:
            requests = 0

            def get_json(self, url):
                return {"value": [{"commitId": "abc123"}]} if "/commits" in url else {"repositoryId": "r"}

            def get(self, *a, **k):
                raise AssertionError("não devia baixar nada")

        wiki = parse_wiki_url(WIKI_URL)
        with mock.patch.object(az, "wiki_root_path", return_value="/Raiz"), \
             mock.patch.dict(ingest._FETCH_CACHE, clear=True), \
             mock.patch.object(ingest, "load_state", return_value={"wiki": {"commit": "abc123"}}):
            result = ingest.fetch_wiki(wiki, FakeClient(), [], 150)
        self.assertTrue(result["unchanged"])

    def test_exclusao_por_padrao_de_caminho(self):
        self.assertTrue(ingest._excluded("RH/Salários 2026", ["rh/"]))
        self.assertFalse(ingest._excluded("Governança Ágil", ["rh/"]))


# ---------- extração, rascunhos e execução ----------

class FakeLLM:
    def __init__(self, replies):
        self.replies, self.calls = list(replies), []

    def chat(self, messages, tools):
        self.calls.append(messages)
        reply = self.replies.pop(0)
        return SimpleNamespace(content=reply if isinstance(reply, str) else json.dumps(reply, ensure_ascii=False), tool_calls=None)


CONCEPTS = {"conceitos": [
    {"nome": "Renegociação", "tipo": "conceito", "sinonimos": ["reneg"], "descricao": "A renegociação troca as condições de uma dívida.",
     "relacoes": [{"rel": "gera", "alvo": "Acordo"}]},
    {"nome": "Ruim/Nome:Inválido", "tipo": "coisa", "descricao": "Texto.", "relacoes": []},
    {"nome": "", "descricao": "sem nome"},
]}


class DraftTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.store = OntologyStore(self.root)
        self.written: dict = {}

    def concept(self, **over):
        return {**ingest.normalize_concepts(CONCEPTS)[0], **over}

    def test_normaliza_nomes_tipos_e_descarta_incompletos(self):
        out = ingest.normalize_concepts(CONCEPTS)
        self.assertEqual([c["nome"] for c in out], ["Renegociação", "Ruim Nome Inválido"])
        self.assertEqual(out[1]["tipo"], "conceito")                 # tipo desconhecido vira conceito
        self.assertEqual(out[0]["relacoes"], [{"rel": "gera", "alvo": "Acordo"}])

    def test_nome_em_maiuscula_e_sinonimos_limpos(self):
        data = {"conceitos": [{"nome": "ata", "descricao": "Texto.", "sinonimos": [
            "Gestao Bussola-violet.md", "Pasta/Ata", "ATA", "ata", "registro da reunião", "registro da reunião"]}]}
        concept = ingest.normalize_concepts(data)[0]
        self.assertEqual(concept["nome"], "Ata")
        self.assertEqual(concept["sinonimos"], ["registro da reunião"])

    def test_cria_rascunho_com_fonte_e_so_dentro_de_rascunhos(self):
        action = ingest.write_draft(self.root, self.store, self.concept(), "wiki:/Governança Ágil", self.written, [])
        self.assertEqual(action, "criado")
        path = self.root / "_rascunhos" / "conceito" / "Renegociação.md"
        meta, body = parse_frontmatter(path.read_text(encoding="utf-8"))
        self.assertEqual(meta["status"], "rascunho")
        self.assertEqual(meta["fontes"], ["wiki:/Governança Ágil"])
        self.assertEqual(meta["relacoes"], [{"rel": "gera", "alvo": "[[Acordo]]"}])
        self.assertIn("troca as condições", body)
        self.assertTrue(self.store.resolve("reneg").is_draft)

    def test_funde_rascunho_existente_unindo_fontes_e_sinonimos(self):
        ingest.write_draft(self.root, self.store, self.concept(), "wiki:/A", self.written, [])
        ingest.write_draft(self.root, self.store, self.concept(sinonimos=["renegociar"], relacoes=[{"rel": "usa", "alvo": "CRM"}]),
                           "wiki:/B", self.written, [])
        meta, _ = parse_frontmatter((self.root / "_rascunhos" / "conceito" / "Renegociação.md").read_text(encoding="utf-8"))
        self.assertEqual(meta["fontes"], ["wiki:/A", "wiki:/B"])
        self.assertEqual(meta["sinonimos"], ["reneg", "renegociar"])
        self.assertEqual([r["rel"] for r in meta["relacoes"]], ["gera", "usa"])

    def test_nunca_sobrescreve_nota_validada(self):
        validated = self.root / "Conceitos" / "Renegociação.md"
        validated.parent.mkdir(parents=True)
        original = "---\ntipo: conceito\n---\nTexto confirmado pelo time."
        validated.write_text(original, encoding="utf-8")
        action = ingest.write_draft(self.root, self.store, self.concept(), "wiki:/A", self.written, [])
        self.assertEqual(action, "atualizacao")
        self.assertEqual(validated.read_text(encoding="utf-8"), original)
        meta, _ = parse_frontmatter((self.root / "_rascunhos" / "conceito" / "Renegociação.md").read_text(encoding="utf-8"))
        self.assertEqual(meta["atualiza"], "[[Renegociação]]")

    def test_conteudo_igual_ao_validado_nao_gera_rascunho(self):
        validated = self.root / "Conceitos" / "Renegociação.md"
        validated.parent.mkdir(parents=True)
        validated.write_text("---\ntipo: conceito\n---\nA renegociação troca as condições de uma dívida.", encoding="utf-8")
        action = ingest.write_draft(self.root, self.store, self.concept(), "wiki:/A", self.written, [])
        self.assertEqual(action, "sem mudança")
        self.assertFalse((self.root / "_rascunhos").exists())

    def test_promover_e_trocar_o_status_mesmo_dentro_de_rascunhos(self):
        ingest.write_draft(self.root, self.store, self.concept(), "wiki:/A", self.written, [])
        path = self.root / "_rascunhos" / "conceito" / "Renegociação.md"
        self.assertTrue(self.store.resolve("Renegociação").is_draft)
        path.write_text(path.read_text(encoding="utf-8").replace("status: rascunho", "status: validado"), encoding="utf-8")
        self.assertFalse(self.store.resolve("Renegociação").is_draft)            # promovida no lugar
        original = path.read_text(encoding="utf-8")
        # uma nova ingestão do mesmo conceito NÃO pode mexer na nota promovida
        action = ingest.write_draft(self.root, self.store, self.concept(descricao="Outra descrição vinda de outra página."),
                                    "wiki:/B", self.written, [])
        self.assertEqual(action, "preservado")
        self.assertEqual(path.read_text(encoding="utf-8"), original)

    def test_status_diferente_de_validado_e_rascunho_mesmo_fora_de_rascunhos(self):
        note = self.root / "Conceitos" / "X.md"
        note.parent.mkdir(parents=True)
        note.write_text("---\nstatus: rascunho\n---\nTexto.", encoding="utf-8")
        self.assertTrue(self.store.resolve("X").is_draft)
        note.write_text("---\nstatus: talvez\n---\nTexto.", encoding="utf-8")
        self.assertTrue(self.store.resolve("X").is_draft)

    def test_preserva_rascunho_editado_a_mao(self):
        ingest.write_draft(self.root, self.store, self.concept(), "wiki:/A", self.written, [])
        path = self.root / "_rascunhos" / "conceito" / "Renegociação.md"
        path.write_text(path.read_text(encoding="utf-8") + "\nAjuste manual do usuário.", encoding="utf-8")
        action = ingest.write_draft(self.root, self.store, self.concept(), "wiki:/B", self.written, [])
        self.assertEqual(action, "preservado")
        self.assertIn("Ajuste manual", path.read_text(encoding="utf-8"))

    def test_avisos_ste_vao_para_o_frontmatter(self):
        text = " ".join(["palavra"] * 30) + "."
        ingest.write_draft(self.root, self.store, self.concept(descricao=text), "wiki:/A", self.written, [])
        content = (self.root / "_rascunhos" / "conceito" / "Renegociação.md").read_text(encoding="utf-8")
        self.assertIn("ste_avisos:", content)
        self.assertIn("frase longa", content)

    def test_dump_e_parse_sao_inversos(self):
        meta = {"tipo": "sistema", "sinonimos": ["a, b", "c"], "relacoes": [{"rel": "usa", "alvo": "CRM"}],
                "fontes": ["wiki:/x: y"], "status": "rascunho", "atualizado": "2026-10-06"}
        parsed, body = parse_frontmatter(dump_note(meta, "Texto."))
        self.assertEqual(parsed["sinonimos"], ["a, b", "c"])
        self.assertEqual(parsed["fontes"], ["wiki:/x: y"])
        self.assertEqual(parsed["relacoes"], [{"rel": "usa", "alvo": "[[CRM]]"}])
        self.assertEqual(body, "Texto.")


class RunIngestTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        tmp = Path(self._tmp.name)
        self.root = tmp / "ont"
        self.settings = {"azure": {"wiki_url": WIKI_URL}, "notion": {"root_page": ""}, "agent": {},
                         "ontology": {"dir": str(self.root), "ingest_max_pages": 150, "ingest_exclude": [], "ingest_max_tokens": 300000}}
        for name, value in (("STATE_PATH", tmp / "state.json"), ("LOG_PATH", tmp / "ingest.log")):
            patcher = mock.patch.object(ingest, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.pages = {"Governança Ágil": "A governança define o fluxo. " * 20, "Retros": "curta",
                      "Credenciais": "senha: SuperSecreta123 " + "texto " * 50}
        self.fetches = 0

    def fetch(self, wiki, client, exclude, max_pages, force=False):
        self.fetches += 1
        state = ingest.load_state()
        if state.get("wiki", {}).get("commit") == "c1" and not force:
            return {"commit": "c1", "pages": {}, "via": "estado", "unchanged": True}
        return {"commit": "c1", "pages": self.pages, "via": "zip", "unchanged": False}

    def go(self, llm=None, **kw):
        with mock.patch.object(ingest, "fetch_wiki", self.fetch):
            return ingest.run_ingest(llm, self.settings, client=SimpleNamespace(requests=1), sleep=lambda s: None, **kw)

    def test_ensaio_nao_chama_o_modelo_nem_grava(self):
        summary = self.go(None, dry_run=True)
        self.assertEqual(summary["wiki"]["paginas_a_processar"], 1)          # a curta e a de segredo ficam de fora
        self.assertEqual(summary["wiki"]["puladas_por_segredo"], 1)
        self.assertEqual(summary["skipped_secrets"], ["Credenciais"])
        self.assertGreater(summary["wiki"]["tokens_estimados"], 0)
        self.assertFalse(self.root.exists())

    def test_execucao_grava_rascunhos_e_a_segunda_nao_faz_nada(self):
        llm = FakeLLM([CONCEPTS])
        summary = self.go(llm, dry_run=False)
        self.assertEqual(summary["drafts"]["criado"], 2)
        self.assertEqual(len(llm.calls), 1)                                  # só a página elegível foi ao modelo
        self.assertNotIn("SuperSecreta123", json.dumps(llm.calls))           # segredo nunca chega ao modelo
        state = json.loads(ingest.STATE_PATH.read_text(encoding="utf-8"))
        self.assertEqual(state["wiki"]["commit"], "c1")                      # nada pendente: commit gravado
        again = self.go(FakeLLM([]), dry_run=False)
        self.assertTrue(again["wiki"]["sem_mudancas"])
        self.assertEqual(again["wiki"]["paginas_a_processar"], 0)

    def test_pagina_alterada_e_reprocessada_pelo_hash(self):
        self.go(FakeLLM([CONCEPTS]), dry_run=False)
        self.pages["Governança Ágil"] += " Frase nova do time."
        summary = self.go(None, dry_run=True, force=True)
        self.assertEqual(summary["wiki"]["paginas_a_processar"], 1)

    def test_limite_nao_grava_o_commit_e_orcamento_interrompe(self):
        self.pages = {f"P{i}": ("A página fala de regras. " * 20) for i in range(3)}
        llm = FakeLLM([{"conceitos": []}] * 3)
        summary = self.go(llm, dry_run=False, limit=1)
        self.assertEqual(len(llm.calls), 1)
        state = json.loads(ingest.STATE_PATH.read_text(encoding="utf-8"))
        self.assertNotIn("commit", state["wiki"])                            # há páginas pendentes
        self.settings["ontology"]["ingest_max_tokens"] = 100
        summary = self.go(FakeLLM([]), dry_run=False)
        self.assertIn("orçamento", summary["stopped"])

    def test_erros_seguidos_interrompem(self):
        self.pages = {f"P{i}": ("A página fala de regras. " * 20) for i in range(8)}
        llm = FakeLLM(["isto não é json"] * 20)
        summary = self.go(llm, dry_run=False)
        self.assertIn("erros seguidos", summary["stopped"])
        self.assertLessEqual(len(summary["errors"]), 5)

    def test_sem_pasta_configurada(self):
        self.settings["ontology"]["dir"] = ""
        with self.assertRaises(ingest.IngestError):
            self.go(None, dry_run=True)

    def test_reescreve_uma_vez_quando_viola_o_padrao(self):
        long_text = " ".join(["palavra"] * 30) + "."
        data = {"conceitos": [{"nome": "Parcela", "tipo": "conceito", "descricao": long_text}]}
        llm = FakeLLM([data, "A parcela é uma fração do acordo."])
        self.pages = {"Parcelas": "texto " * 80}
        self.go(llm, dry_run=False)
        self.assertEqual(len(llm.calls), 2)                                  # extração + 1 reescrita
        content = (self.root / "_rascunhos" / "conceito" / "Parcela.md").read_text(encoding="utf-8")
        self.assertIn("fração do acordo", content)
        self.assertNotIn("ste_avisos", content)


class RetryTests(unittest.TestCase):
    def test_429_do_modelo_espera_retry_after(self):
        error = Exception("429")
        error.status_code = 429
        error.response = SimpleNamespace(headers={"retry-after": "3"})
        sleeps = []

        class Flaky:
            n = 0

            def chat(self, messages, tools):
                Flaky.n += 1
                if Flaky.n == 1:
                    raise error
                return SimpleNamespace(content="ok")

        self.assertEqual(ingest.chat_with_retry(Flaky(), [], sleeps.append).content, "ok")
        self.assertEqual(sleeps, [3.0])

    def test_outros_erros_sobem(self):
        class Broken:
            def chat(self, messages, tools):
                raise ValueError("falha")

        with self.assertRaises(ValueError):
            ingest.chat_with_retry(Broken(), [], lambda s: None)


if __name__ == "__main__":
    unittest.main()
