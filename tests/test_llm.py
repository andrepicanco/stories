"""Cliente LLM via gateway LiteLLM: configuração lida do ambiente."""
import os
import unittest
from unittest import mock

from agent.llm import LLM, LLMConfigError

ENV = {"LITELLM_BASE_URL": "https://gateway.test/v1", "LITELLM_API_KEY": "k", "LITELLM_MODEL": "model-a"}


class ClientConfigTests(unittest.TestCase):
    def test_client_uses_gateway_url_key_and_model_from_env(self):
        with mock.patch.dict(os.environ, ENV):
            llm = LLM()
        self.assertEqual(str(llm.client.base_url), "https://gateway.test/v1/")
        self.assertEqual(llm.client.api_key, "k")
        self.assertEqual(llm.model, "model-a")

    def test_base_url_without_scheme_gets_https(self):
        with mock.patch.dict(os.environ, {**ENV, "LITELLM_BASE_URL": "gateway.test/v1"}):
            self.assertEqual(str(LLM().client.base_url), "https://gateway.test/v1/")

    def test_missing_variables_are_listed(self):
        with mock.patch.dict(os.environ, ENV):
            os.environ.pop("LITELLM_MODEL")
            with self.assertRaisesRegex(LLMConfigError, "LITELLM_MODEL"):
                LLM()


if __name__ == "__main__":
    unittest.main()
