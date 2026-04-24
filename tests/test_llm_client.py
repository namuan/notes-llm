import os
import unittest
from unittest.mock import patch

from llm_client import LLMClient, LLMProfile, NoteUpdate


class LLMClientTests(unittest.TestCase):
    def test_resolve_api_key_prefers_env(self) -> None:
        profile = LLMProfile(
            name="test",
            base_url="https://example.com/v1/",
            model="x",
            api_key_env="TEST_API_KEY",
            api_key_value="fallback",
        )
        with patch.dict(os.environ, {"TEST_API_KEY": "from-env"}, clear=False):
            self.assertEqual(LLMClient._resolve_api_key(profile), "from-env")

    def test_build_client_uses_azure_for_azure_urls(self) -> None:
        profile = LLMProfile(
            name="azure",
            base_url="https://example.openai.azure.com/openai/deployments/demo/",
            model="gpt-4o",
        )
        sentinel = object()
        with patch("llm_client.AzureOpenAI", return_value=sentinel) as azure_ctor:
            client = LLMClient._build_client(profile)
        self.assertIs(client, sentinel)
        azure_ctor.assert_called_once()

    def test_parse_response_extracts_notes(self) -> None:
        fake_client = object.__new__(LLMClient)
        parsed = fake_client._parse_response(
            """
            <wiki_updates>
              <note action="create" subfolder="Sources" title="Summary: Test">
                Hello
              </note>
              <note action="update" subfolder="" title="_Index">
                Index body
              </note>
              <log_entry>Updated wiki</log_entry>
            </wiki_updates>
            """
        )
        self.assertEqual(parsed.log_entry, "Updated wiki")
        self.assertEqual(
            parsed.notes,
            [
                NoteUpdate(
                    action="create",
                    subfolder="Sources",
                    title="Summary: Test",
                    markdown_content="Hello",
                ),
                NoteUpdate(
                    action="update",
                    subfolder="",
                    title="_Index",
                    markdown_content="Index body",
                ),
            ],
        )


if __name__ == "__main__":
    unittest.main()
