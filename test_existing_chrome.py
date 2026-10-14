"""Testes offline do Chrome pessoal (sem acesso ao Chrome ou credenciais)."""
import asyncio
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch, AsyncMock

from business_suite_forms import (discover_fields, plan_form_values, validate_media_files)
from existing_chrome import (
    ChromeMCP, chrome_connection_args, extract_text, parse_business_pages,
    server_command, unique_uid, CAPTION_TERMS, UPLOAD_TERMS,
    connection_failure_details, describe_mcp_tool_error,
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

    def test_mcp_new_list_pages_title_before_url(self):
        """Regressao Chrome DevTools MCP: ID: Titulo (URL) [selected]."""
        output = (
            '## Pages\n'
            '0: ArayFlow GitHub (https://github.com/llongaray/ArayFlow)\n'
            '3: Meta Business Suite (https://business.facebook.com/latest/home?business_id=123) [selected]\n'
            '5: Other (https://business.facebook.com.evil.invalid/)\n'
            '6: Login (https://www.facebook.com/login)\n'
        )
        self.assertEqual(parse_business_pages(output), [3])

    def test_mcp_url_as_title_and_old_format_mixed(self):
        output = (
            '## Pages\n'
            '1: business.facebook.com/latest/home (https://business.facebook.com/latest/home) [selected]\n'
            '2: https://business.facebook.com/latest/planner\n'
            '3: https://mail.google.com/\n'
        )
        self.assertEqual(parse_business_pages(output), [1, 2])

    def test_mcp_title_form_reuses_meta_tab_without_opening_more(self):
        fake = FakeSession(
            '## Pages\n1: Google (https://google.com/)\n'
            '2: Meta Business Suite (https://business.facebook.com/latest/home) [selected]'
        )
        page = asyncio.run(ChromeMCP(fake).meta_page())
        self.assertEqual(page, 2)
        self.assertNotIn("new_page", [tool for tool, _ in fake.calls])
        self.assertIn(("select_page", {"pageId": 2, "bringToFront": True}), fake.calls)

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

    def test_business_suite_root_with_query_is_recognized(self):
        pages = (
            "## Pages\n0: https://business.facebook.com?business_id=1234 [selected]\n"
            "1: https://business.facebook.com.evil.invalid/latest/home\n"
            "2: https://www.facebook.com/login"
        )
        self.assertEqual(parse_business_pages(pages), [0])

    def test_inspect_requires_existing_business_tab_and_does_not_open_new(self):
        fake = FakeSession("## Pages\n1: https://www.facebook.com/login")
        with self.assertRaisesRegex(RuntimeError, "Abra"):
            asyncio.run(ChromeMCP(fake).meta_page(create_if_missing=False))
        names = [name for name, _ in fake.calls]
        self.assertNotIn("new_page", names)
        self.assertNotIn("select_page", names)

    def test_new_suite_tab_can_take_time_to_appear(self):
        class DelayedSession(FakeSession):
            def __init__(self):
                super().__init__("## Pages\n1: https://www.facebook.com/login")
                self.polls = 0
                self.opened = False

            async def call_tool(self, name, arguments=None):
                self.calls.append((name, arguments))
                if name == "new_page":
                    self.opened = True
                    return reply("Aba solicitada")
                if name == "list_pages":
                    self.polls += 1
                    if self.opened and self.polls >= 3:
                        return reply("## Pages\n2: https://business.facebook.com/latest/home")
                    return reply(self.pages)
                return reply("OK")

        fake = DelayedSession()
        with patch("existing_chrome.asyncio.sleep", new_callable=AsyncMock):
            result = asyncio.run(ChromeMCP(fake).meta_page())
        self.assertEqual(result, 2)
        self.assertEqual(sum(name == "new_page" for name, _ in fake.calls), 1)

    def test_chrome_opening_falls_back_to_manual_login_and_recheck(self):
        class LoginRedirectSession(FakeSession):
            def __init__(self):
                super().__init__("## Pages\n1: https://www.facebook.com/login")
                self.requests = 0
                self.login_complete = False

            async def call_tool(self, name, arguments=None):
                self.calls.append((name, arguments))
                if name == "new_page":
                    self.requests += 1
                    return reply("Pagina Meta aberta, aguarde login")
                if name == "list_pages":
                    if self.login_complete:
                        return reply("## Pages\n2: https://business.facebook.com/latest/home")
                    return reply(self.pages)
                return reply("OK")

        fake = LoginRedirectSession()
        def finish_login(_prompt):
            fake.login_complete = True
            return "VERIFICAR ABA"

        with patch("existing_chrome.asyncio.sleep", new_callable=AsyncMock), \
             patch("builtins.input", side_effect=finish_login):
            page_id = asyncio.run(ChromeMCP(fake).meta_page())
        self.assertEqual(page_id, 2)
        self.assertEqual(fake.requests, 1)
        self.assertIn(("select_page", {"pageId": 2, "bringToFront": True}), fake.calls)

    def test_chrome_opening_can_be_cancelled_after_login_redirect(self):
        fake = FakeSession("## Pages\n1: https://www.facebook.com/login")
        # Esta sessao falsa continua redirecionada mesmo apos new_page.
        class RedirectSession(FakeSession):
            async def call_tool(self, name, arguments=None):
                if name == "new_page":
                    self.calls.append((name, arguments))
                    return reply("Redirect to login")
                return await super().call_tool(name, arguments)

        fake = RedirectSession(fake.pages)
        with patch("existing_chrome.asyncio.sleep", new_callable=AsyncMock), \
             patch("builtins.input", return_value=""):
            with self.assertRaisesRegex(RuntimeError, "nenhuma aba"):
                asyncio.run(ChromeMCP(fake).meta_page())
        self.assertEqual(sum(name == "new_page" for name, _ in fake.calls), 1)

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
        self.assertIn("fill_form", calls)

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

    def test_schedule_date_time_and_caption_are_filled_together(self):
        fields = (
            'uid=5_1 textbox "Legenda" multiline\n'
            'uid=5_2 textbox "Data da publicação"\n'
            'uid=5_3 textbox "Horário da publicação"\n'
            'uid=5_4 button "Agendar"'
        )
        fake = FakeSession(
            "## Pages\n1: https://business.facebook.com/latest/composer", [fields, fields]
        )
        when = datetime.now(ZoneInfo("America/Sao_Paulo")) + timedelta(days=2)
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "slide.png"
            path.write_bytes(b"PNG")
            result = asyncio.run(ChromeMCP(fake).prefill(
                1, [path], "Nova legenda com #hashtags", when,
            ))
        self.assertEqual(result, {
            "images": False, "caption": True, "date": True, "time": True
        })
        form_calls = [args for name, args in fake.calls if name == "fill_form"]
        self.assertEqual(len(form_calls), 1)
        self.assertEqual(form_calls[0]["elements"], [
            {"uid": "5_1", "value": "Nova legenda com #hashtags"},
            {"uid": "5_2", "value": when.strftime("%d/%m/%Y")},
            {"uid": "5_3", "value": when.strftime("%H:%M")},
        ])
        self.assertNotIn("click", [name for name, _ in fake.calls])

    def test_missing_time_never_updates_date(self):
        fields = (
            'uid=4_1 textbox "Legenda"\n'
            'uid=4_2 textbox "Data de agendamento"\n'
            'uid=4_3 button "Agendar"'
        )
        fake = FakeSession(
            "## Pages\n1: https://business.facebook.com/latest/composer", [fields, fields]
        )
        when = datetime.now(ZoneInfo("America/Sao_Paulo")) + timedelta(days=2)
        result = asyncio.run(ChromeMCP(fake).prefill(1, [], "Legenda", when))
        self.assertEqual(result["date"], False)
        self.assertEqual(result["time"], False)
        forms = [args["elements"] for name, args in fake.calls if name == "fill_form"]
        self.assertEqual(forms, [[{"uid": "4_1", "value": "Legenda"}]])

    def test_fails_closed_when_operator_navigates_to_another_site(self):
        fake = FakeSession("## Pages\n1: https://mail.google.com/")
        when = datetime.now(ZoneInfo("America/Sao_Paulo")) + timedelta(days=2)
        with self.assertRaisesRegex(RuntimeError, "business.facebook.com"):
            asyncio.run(ChromeMCP(fake).prefill(1, [], "Legenda", when))
        names = [name for name, _ in fake.calls]
        self.assertEqual(names, ["list_pages"])

    def test_mapping_rejects_duplicate_accessibility_labels(self):
        snapshot = (
            'uid=2_1 textbox "Legenda"\n'
            'uid=2_2 textbox "Legenda"\n'
            'uid=2_3 textbox "Data"\n'
            'uid=2_4 textbox "Data"\n'
            'uid=2_5 textbox "Horário"\n'
            'uid=2_6 button "Agendar"'
        )
        fields = discover_fields(snapshot)
        self.assertIsNone(fields.caption_uid)
        self.assertIsNone(fields.date_uid)
        self.assertIsNone(fields.time_uid)
        self.assertIn("legenda", fields.ambiguous)
        self.assertIn("data", fields.ambiguous)

    def test_submit_controls_never_selected_as_schedule_inputs(self):
        snapshot = (
            'uid=3_1 button "Agendar"\n'
            'uid=3_2 button "Publicar"\n'
            'uid=3_3 button "Programar publicação"'
        )
        fields = discover_fields(snapshot)
        self.assertFalse(any((fields.date_uid, fields.time_uid,
                              fields.caption_uid, fields.upload_uid)))

    def test_date_fields_require_timezone(self):
        fields = discover_fields(
            'uid=1_1 textbox "Data"\nuid=1_2 textbox "Horário"'
        )
        with self.assertRaisesRegex(ValueError, "fuso"):
            plan_form_values(fields, "Legenda", datetime(2027, 1, 1, 7, 0))

    def test_media_validation_refuses_missing_and_wrong_extensions(self):
        with self.assertRaises(ValueError):
            validate_media_files([Path("missing_file.png")])
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "slide.txt"
            path.write_text("nao e arte")
            with self.assertRaises(ValueError):
                validate_media_files([path])

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

    def test_default_connection_uses_debugging_port(self):
        with tempfile.TemporaryDirectory() as folder:
            port_file = Path(folder) / "DevToolsActivePort"
            port_file.write_text("9222\n/devtools/browser/abc-def\n", encoding="utf-8")
            with patch.dict(os.environ, {
                "ARAYFLOW_CHROME_USER_DATA": folder,
                "ARAYFLOW_CHROME_BROWSER_URL": "active-port",
            }):
                args = chrome_connection_args()
        self.assertEqual(args, ["--wsEndpoint", "ws://127.0.0.1:9222/devtools/browser/abc-def"])

    def test_classic_browser_url_remains_available(self):
        with patch.dict(os.environ, {"ARAYFLOW_CHROME_BROWSER_URL": "http://127.0.0.1:9222"}):
            self.assertEqual(
                chrome_connection_args(),
                ["--browserUrl", "http://127.0.0.1:9222"],
            )

    def test_auto_connect_remains_optional(self):
        with patch.dict(os.environ, {"ARAYFLOW_CHROME_BROWSER_URL": "auto"}):
            self.assertEqual(chrome_connection_args(), ["--autoConnect"])

    def test_remote_chrome_address_is_rejected(self):
        with patch.dict(os.environ, {"ARAYFLOW_CHROME_BROWSER_URL": "http://example.com:9222"}):
            with self.assertRaises(ValueError):
                chrome_connection_args()

    def test_server_command_passes_explicit_port(self):
        with patch("existing_chrome.shutil.which", return_value="npx"), \
             patch.dict(os.environ, {"ARAYFLOW_CHROME_BROWSER_URL": "http://127.0.0.1:9222"}):
            _command, args = server_command()
        joined = " ".join(args)
        self.assertIn("--browserUrl http://127.0.0.1:9222", joined)
        self.assertNotIn("--autoConnect", joined)
        self.assertNotIn("--wsEndpoint", joined)

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
