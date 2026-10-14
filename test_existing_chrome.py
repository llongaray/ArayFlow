"""Testes offline do Chrome pessoal (sem acesso ao Chrome ou credenciais)."""
import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from existing_chrome import (
    ChromeMCP, extract_text, parse_business_pages, server_command, unique_uid,
    CAPTION_TERMS, UPLOAD_TERMS, connection_failure_details, describe_mcp_tool_error,
)
import re


def reply(text: str = "", *, error=False):
    return SimpleNamespace(
        isError=error,
        content=[SimpleNamespace(type="text", text=text)],
    )


class FakeSession:
    def __init__(self, pages, snapshots=None):
        self.pages = pages
        self.snapshots = snapshots or []
        self.calls = []

    async def call_tool(self, name, arguments=None):
        self.calls.append((name, arguments))
        if name == "list_pages":
            return reply(self.pages)
        if name == "new_page":
            self.pages = "## Pages\n1: https://business.facebook.com/latest/home [selected]"
            return reply("Pagina aberta")
        if name == "take_snapshot":
            return reply(self.snapshots.pop(0) if self.snapshots else "")
        return reply("OK")


class ExistingChromeTests(unittest.TestCase):
    def test_only_business_suite_tabs_selected(self):
        output = (
            "## Pages\n1: https://mail.google.com/ [selected]\n"
            "2: https://business.facebook.com/latest/home\n"
            "3: https://github.com/\n"
            "4: https://business.facebook.com/latest/planner"
        )
        self.assertEqual(parse_business_pages(output), [2, 4])

    def test_existing_business_tab_is_reused_without_new_browser(self):
        fake = FakeSession(
            "## Pages\n1: https://google.com/\n"
            "2: https://business.facebook.com/latest/home [selected]"
        )
        page = asyncio.run(ChromeMCP(fake).meta_page())
        self.assertEqual(page, 2)
        self.assertNotIn("new_page", [call[0] for call in fake.calls])
        self.assertIn(("select_page", {"pageId": 2, "bringToFront": True}), fake.calls)

    def test_only_new_tab_when_no_suite_tab_found(self):
        fake = FakeSession("## Pages\n1: https://google.com/")
        page = asyncio.run(ChromeMCP(fake).meta_page())
        self.assertEqual(page, 1)
        self.assertEqual([call[0] for call in fake.calls].count("new_page"), 1)
        self.assertIn(
            ("new_page", {"url": "https://business.facebook.com/", "background": False}),
            fake.calls,
        )

    def test_unambiguous_fields_prefill_without_schedule_click(self):
        fake = FakeSession(
            "## Pages\n1: https://business.facebook.com/",
            [
                'uid=3_1 button "Adicionar fotos"\nuid=3_2 textbox "Legenda"',
                'uid=4_1 textbox "Legenda"\nuid=4_2 button "Agendar"',
            ],
        )
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "slide.png"
            path.write_bytes(b"PNG")
            result = asyncio.run(ChromeMCP(fake).prefill(1, [path], "Legenda do post"))
            self.assertEqual(result, {"images": True, "caption": True})
        calls = [name for name, _ in fake.calls]
        self.assertNotIn("click", calls)
        self.assertNotIn("press_key", calls)
        self.assertIn("upload_file", calls)
        self.assertIn("fill", calls)

    def test_ambiguous_controls_always_require_manual_review(self):
        fake = FakeSession(
            "## Pages\n1: https://business.facebook.com/",
            [
                'uid=1_1 button "Adicionar fotos"\nuid=1_2 button "Adicionar fotos"',
                'uid=2_1 textbox "Legenda"\nuid=2_2 textbox "Legenda"',
            ],
        )
        result = asyncio.run(ChromeMCP(fake).prefill(1, [Path("slide.png")], "Teste"))
        self.assertEqual(result, {"images": False, "caption": False})
        self.assertNotIn("upload_file", [name for name, _ in fake.calls])
        self.assertNotIn("fill", [name for name, _ in fake.calls])

    def test_invalid_tool_result_is_not_ignored(self):
        class Failure:
            async def call_tool(self, name, arguments=None):
                return reply("irrelevant", error=True)
        with self.assertRaisesRegex(RuntimeError, "Chrome DevTools MCP"):
            asyncio.run(ChromeMCP(Failure()).call("list_pages"))

    def test_connection_error_unwraps_nested_exception_groups(self):
        inner = RuntimeError("Chrome remote debugging is disabled")
        grouped = ExceptionGroup("MCP transport failed", [inner])
        summary = connection_failure_details(grouped)
        self.assertIn("ExceptionGroup", summary)
        self.assertIn("Chrome remote debugging is disabled", summary)

    def test_diagnostics_mask_private_urls_and_tokens(self):
        error = RuntimeError(
            "Unable to connect https://example.invalid/hidden?token=abc123 "
            "authorization:BearerPrivate cookie=sessionvalue"
        )
        summary = connection_failure_details(error)
        self.assertNotIn("example.invalid", summary)
        self.assertNotIn("abc123", summary)
        self.assertNotIn("BearerPrivate", summary)
        self.assertNotIn("sessionvalue", summary)
        self.assertIn("[URL]", summary)

    def test_list_pages_timeout_explains_problem_without_leaking_data(self):
        result = reply(
            "ProtocolError: Network.enable timed out. "
            "URL https://business.facebook.com/?session=secret123 "
            "Authorization:Bearer abcdef", error=True
        )
        description = describe_mcp_tool_error(result)
        self.assertIn("Network.enable", description)
        self.assertNotIn("secret123", description)
        self.assertNotIn("abcdef", description)

        class FailedSession:
            async def call_tool(self, name, arguments=None):
                return result

        with self.assertRaisesRegex(RuntimeError, "Network.enable"):
            asyncio.run(ChromeMCP(FailedSession()).call("list_pages"))

    def test_devtools_active_port_reports_specific_diagnostic(self):
        result = reply(
            "Could not find DevToolsActivePort in Chrome profile. "
            "cookie=my_private_session", error=True
        )
        self.assertIn("DevToolsActivePort", describe_mcp_tool_error(result))
        self.assertNotIn("my_private_session", describe_mcp_tool_error(result))

    def test_unknown_browser_tool_error_is_redacted(self):
        result = reply(
            "Unknown: https://mail.google.com/?token=supersecret", error=True
        )
        diagnosis = describe_mcp_tool_error(result)
        self.assertIn("nao classificada", diagnosis)
        self.assertNotIn("mail.google.com", diagnosis)
        self.assertNotIn("supersecret", diagnosis)

    def test_node_missing_has_actionable_error(self):
        with patch("existing_chrome.shutil.which", return_value=None):
            with self.assertRaisesRegex(RuntimeError, "Node.js nao encontrado"):
                server_command()

    def test_caption_matches_only_single_label(self):
        sample = 'uid=3_1 textbox "Legenda"\nuid=3_2 textbox "Legenda"'
        self.assertIsNone(unique_uid(sample, CAPTION_TERMS, re.compile("textbox")))

    def test_upload_does_not_match_publish_button(self):
        sample = 'uid=3_1 button "Publicar"\nuid=3_2 button "Agendar"'
        self.assertIsNone(unique_uid(sample, UPLOAD_TERMS, re.compile("button")))


if __name__ == "__main__":
    unittest.main()
