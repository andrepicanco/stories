import importlib
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from integrations import azure_client as az
from integrations.wiki_url import InvalidWikiUrl, WikiContext, parse_wiki_url

BSF_URL = ("https://dev.azure.com/BemolDigital/Bemol%20Servi%C3%A7os%20Financeiros/_wiki/wikis/"
           "Bemol-Servi%C3%A7os-Financeiros.wiki/10122/%F0%9F%92%9C-Violet-(Cobran%C3%A7a)")


class WikiUrlTests(unittest.TestCase):
    def test_parse_url_da_wiki_bsf(self):
        w = parse_wiki_url(BSF_URL)
        self.assertEqual(w.org_url, "https://dev.azure.com/BemolDigital")
        self.assertEqual(w.project, "Bemol Serviços Financeiros")
        self.assertEqual(w.wiki, "Bemol-Serviços-Financeiros.wiki")
        self.assertEqual(w.page_id, 10122)
        self.assertEqual(w.slug, "💜-Violet-(Cobrança)")

    def test_url_sem_pagina_usa_a_wiki_inteira(self):
        w = parse_wiki_url("https://dev.azure.com/org/proj/_wiki/wikis/minha.wiki")
        self.assertIsNone(w.page_id)

    def test_urls_invalidas(self):
        for bad in ("", "https://exemplo.com/a/b/_wiki/wikis/w", "https://dev.azure.com/org/proj/_boards/board/t/x"):
            with self.assertRaises(InvalidWikiUrl):
                parse_wiki_url(bad)


class WikiPathTests(unittest.TestCase):
    def setUp(self):
        self.wiki = WikiContext("https://dev.azure.com/o", "p", "w", None, "")

    def test_caminho_relativo_vira_absoluto_sob_a_raiz(self):
        with mock.patch.object(az, "wiki_root_path", return_value="/💜 Violet (Cobrança)"):
            self.assertEqual(az._wiki_abs(self.wiki, "Regras/Multa"), "/💜 Violet (Cobrança)/Regras/Multa")
            self.assertEqual(az._wiki_abs(self.wiki, ""), "/💜 Violet (Cobrança)")
            self.assertEqual(az._wiki_relative(self.wiki, "/💜 Violet (Cobrança)/Regras"), "Regras")

    def test_recusa_sair_da_raiz(self):
        with mock.patch.object(az, "wiki_root_path", return_value="/Raiz"):
            with self.assertRaises(az.AzureError):
                az._wiki_abs(self.wiki, "../Outra")

    def test_busca_por_titulo_sem_acento_e_com_todas_as_palavras(self):
        tree = ["Governança Ágil", "Regras/Multa de Atraso", "Regras/Juros", "Operacional"]
        with mock.patch.object(az, "wiki_list_pages", return_value=tree):
            self.assertEqual(az.wiki_search(self.wiki, "governanca agil"), ["Governança Ágil"])
            self.assertEqual(az.wiki_search(self.wiki, "MULTA atraso"), ["Regras/Multa de Atraso"])
            self.assertEqual(az.wiki_search(self.wiki, "inexistente"), [])
            self.assertEqual(az.wiki_search(self.wiki, "  "), [])


class HistoryDeleteTests(unittest.TestCase):
    def test_delete_remove_so_a_historia_pedida(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "h.db"
            with mock.patch.dict(os.environ, {"STORIES_DB_PATH": str(db)}):
                from server import history
                importlib.reload(history)
                try:
                    a, b = history.create("A"), history.create("B")
                    self.assertTrue(history.delete(a["id"]))
                    self.assertFalse(history.delete(a["id"]))
                    self.assertEqual([s["id"] for s in history.list_recent()], [b["id"]])
                finally:
                    pass
            importlib.reload(history)   # volta ao caminho padrão para os demais testes


if __name__ == "__main__":
    unittest.main()
