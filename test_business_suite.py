"""Testes offline do assistente Business Suite v0.7. Sem navegador ou credenciais."""
import tempfile
import re
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock, patch

from business_suite_store import BusinessSuiteStore
from publication_store import PublicationStore
from business_suite_assistant import approved_rows, try_prefill, launch_chrome_context
from dashboard import create_app

POST_ID = "ARAY-20261014-002"
DAY = "2026-10-14"
DUE = "2026-10-14T09:00:00-03:00"

class MetaSuiteTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.db = self.root / "data" / "arayflow.sqlite3"

    def tearDown(self):
        self.temp.cleanup()

    def test_reservation_persists_and_requires_confirmation(self):
        store = BusinessSuiteStore(self.db)
        self.assertTrue(store.reserve(POST_ID, DUE))
        self.assertFalse(store.reserve(POST_ID, DUE))
        self.assertEqual(store.get(POST_ID)["status"], "awaiting_confirmation")
        self.assertTrue(store.update(POST_ID, "awaiting_confirmation", "scheduled", "confirmado"))
        self.assertFalse(store.update(POST_ID, "awaiting_confirmation", "scheduled"))
        store.close()
        again = BusinessSuiteStore(self.db)
        self.assertEqual(again.get(POST_ID)["status"], "scheduled")
        again.close()

    def test_prepared_api_prevents_suite_duplicate(self):
        pub = PublicationStore(self.db)
        pub.set(POST_ID, "prepared", container_id="123")
        pub.close()
        store = BusinessSuiteStore(self.db)
        self.assertFalse(store.reserve(POST_ID, DUE))
        self.assertIsNone(store.get(POST_ID))
        store.close()

    def test_suite_prevents_api_duplicate(self):
        store = BusinessSuiteStore(self.db)
        self.assertTrue(store.reserve(POST_ID, DUE))
        store.close()
        pub = PublicationStore(self.db)
        self.assertTrue(pub.business_suite_reserved(POST_ID))
        self.assertFalse(pub.claim(POST_ID))
        self.assertIsNone(pub.get(POST_ID))
        pub.close()

    def test_unknown_status_rejected(self):
        store = BusinessSuiteStore(self.db)
        self.assertTrue(store.reserve(POST_ID, DUE))
        with self.assertRaises(ValueError):
            store.update(POST_ID, "awaiting_confirmation", "published")
        store.close()

    def test_manual_fallback_on_ambiguous_composer(self):
        class Ambiguous:
            def count(self): return 2
            def nth(self, index): return self
            def get_attribute(self, name): return "image/png"
            def is_visible(self): return True
        class BrowserPage:
            def locator(self, *args): return Ambiguous()
            def get_by_role(self, *args, **kwargs): return Ambiguous()
            def get_by_placeholder(self, *args, **kwargs): return Ambiguous()
        self.assertEqual(try_prefill(BrowserPage(), [Path("test.png")], "Legenda"),
                         {"images": False, "caption": False})

    def test_uses_installed_chrome_with_persistent_separate_profile(self):
        playwright = Mock()
        browser_context = object()
        playwright.chromium.launch_persistent_context.return_value = browser_context
        with tempfile.TemporaryDirectory() as folder:
            profile = Path(folder) / "playwright_chrome_profile"
            result = launch_chrome_context(playwright, profile)
            self.assertIs(result, browser_context)
            kwargs = playwright.chromium.launch_persistent_context.call_args.kwargs
            self.assertEqual(kwargs["channel"], "chrome")
            self.assertEqual(kwargs["user_data_dir"], str(profile))
            self.assertFalse(kwargs["headless"])
            self.assertTrue(profile.is_dir())
            # Perfil nao e eliminado ao fechar uma sessao; arquivos persistem.
            marker = profile / "session-check.txt"
            marker.write_text("persist", encoding="utf-8")
            launch_chrome_context(playwright, profile)
            self.assertEqual(marker.read_text(encoding="utf-8"), "persist")

    def test_chrome_missing_has_actionable_error(self):
        playwright = Mock()
        playwright.chromium.launch_persistent_context.side_effect = RuntimeError(
            "Executable doesn't exist at C:/Program Files/Google/Chrome/Application/chrome.exe"
        )
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(RuntimeError, "Google Chrome nao encontrado"):
                launch_chrome_context(playwright, Path(folder) / "chrome")

    def test_rejects_reusing_busy_arayflow_profile(self):
        playwright = Mock()
        playwright.chromium.launch_persistent_context.side_effect = RuntimeError(
            "ProcessSingleton: user data directory is already in use"
        )
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(RuntimeError, "ja esta aberto"):
                launch_chrome_context(playwright, Path(folder) / "chrome")

    def test_local_dashboard_get_and_no_destructive_actions(self):
        row = {
            "ID": POST_ID, "Data": "14/10/2026", "Horário": "09:00",
            "Tipo": "Imagem única", "Status": "Aprovado",
            "Legenda pronta": "Teste de interface", "Qtd. imagens": "1",
            "Pasta das imagens": "https://drive.google.com/drive/folders/123"
        }
        store = BusinessSuiteStore(self.db)
        store.reserve(POST_ID, DUE)
        store.update(POST_ID, "awaiting_confirmation", "scheduled")
        store.close()
        app = create_app(root=self.root)
        app.config["TESTING"] = True
        with patch("dashboard.get_calendar", return_value=[row]), \
             patch("dashboard.task_state", return_value="Ready"):
            response = app.test_client().get("/?date=2026-10-14",
                                              headers={"Host": "localhost"})
        self.assertEqual(response.status_code, 200)
        text = response.get_data(as_text=True)
        self.assertIn("ARAY-20261014-002", text)
        self.assertIn("business_suite_assistant.py", text)
        self.assertIn("scheduled", text)

    def test_pause_with_signed_token_without_session_cookie(self):
        app = create_app(root=self.root)
        app.config["TESTING"] = True
        with patch("dashboard.get_calendar", return_value=[]), \
             patch("dashboard.task_state", return_value="Ready"):
            response = app.test_client().get("/", headers={"Host": "127.0.0.1:8766"})
        self.assertEqual(response.status_code, 200)
        markup = response.get_data(as_text=True)
        match = re.search(
            r'<form[^>]+action="/scheduler/pause"[^>]*>.*?'
            r'<input[^>]+name="csrf"[^>]+value="([^"]+)"',
            markup, re.S,
        )
        self.assertIsNotNone(match, "Formulario de pausa deve incluir token assinado")
        with patch("dashboard.change_task") as change_task:
            # Novo cliente SEM cookie de sessao, mas com token assinado valido.
            posted = app.test_client().post(
                "/scheduler/pause", data={"confirmation": "PAUSAR", "csrf": match.group(1)},
                headers={"Host": "127.0.0.1:8766", "Origin": "http://127.0.0.1:8766"},
            )
        self.assertEqual(posted.status_code, 302)
        change_task.assert_called_once_with("pause")

    def test_pause_rejects_missing_or_wrong_action_token(self):
        app = create_app(root=self.root)
        app.config["TESTING"] = True
        response = app.test_client().post(
            "/scheduler/pause", data={"confirmation": "PAUSAR"},
            headers={"Host": "127.0.0.1:8766", "Origin": "http://127.0.0.1:8766"},
        )
        self.assertEqual(response.status_code, 403)
        with patch("dashboard.get_calendar", return_value=[]), \
             patch("dashboard.task_state", return_value="Ready"):
            page = app.test_client().get("/", headers={"Host": "127.0.0.1:8766"})
        token = re.search(
            r'<form[^>]+action="/scheduler/pause"[^>]*>.*?'
            r'<input[^>]+name="csrf"[^>]+value="([^"]+)"',
            page.get_data(as_text=True), re.S,
        )
        self.assertIsNotNone(token)
        with patch("dashboard.change_task") as change_task:
            wrong = app.test_client().post(
                "/scheduler/resume",
                data={"csrf": token.group(1), "confirmation": "RETOMAR"},
                headers={"Host": "127.0.0.1:8766"},
            )
            invalid_origin = app.test_client().post(
                "/scheduler/pause",
                data={"csrf": token.group(1), "confirmation": "PAUSAR"},
                headers={"Host": "127.0.0.1:8766", "Origin": "https://example.invalid"},
            )
        self.assertEqual(wrong.status_code, 403)
        self.assertEqual(invalid_origin.status_code, 403)
        change_task.assert_not_called()

    def test_business_suite_start_accepts_localhost_alias_origin(self):
        """Regressao: POST feito a 127.0.0.1 com Origin localhost e valido."""
        import os
        py = self.root / ".venv" / "Scripts" / "python.exe"
        py.parent.mkdir(parents=True, exist_ok=True)
        py.write_text("", encoding="utf-8")
        (self.root / "business_suite_assistant.py").write_text("", encoding="utf-8")
        app = create_app(root=self.root)
        app.config["TESTING"] = True
        with patch.dict(os.environ, {"ARAYFLOW_AUTOPUBLISH_ENABLED": "false"}), \
             patch("dashboard.get_calendar", return_value=[]), \
             patch("dashboard.task_state", return_value="Disabled"), \
             patch("dashboard.sys.platform", "win32"), \
             patch("dashboard.subprocess.CREATE_NEW_CONSOLE", 16, create=True), \
             patch("dashboard.subprocess.Popen") as popen:
            page = app.test_client().get("/?date=2026-10-14",
                                         headers={"Host": "127.0.0.1:8766"})
            self.assertEqual(page.status_code, 200)
            token = re.search(
                r'<form[^>]+action="/business-suite/start"[^>]*>.*?'
                r'<input[^>]+name="csrf"[^>]+value="([^"]+)"',
                page.get_data(as_text=True), re.S,
            )
            self.assertIsNotNone(token)
            posted = app.test_client().post(
                "/business-suite/start",
                data={"csrf": token.group(1), "confirmation": "ABRIR",
                      "date": "2026-10-14"},
                headers={"Host": "127.0.0.1:8766", "Origin": "http://localhost:8766"},
            )
            self.assertEqual(posted.status_code, 302)
            popen.assert_called_once()

    def test_business_suite_null_origin_from_same_origin_chrome(self):
        """Regressao: Chrome envia Origin=null, mas Sec-Fetch-Site=same-origin."""
        import os
        py = self.root / ".venv" / "Scripts" / "python.exe"
        py.parent.mkdir(parents=True, exist_ok=True)
        py.write_text("", encoding="utf-8")
        (self.root / "business_suite_assistant.py").write_text("", encoding="utf-8")
        app = create_app(root=self.root)
        app.config["TESTING"] = True
        with (
            patch.dict(os.environ, {"ARAYFLOW_AUTOPUBLISH_ENABLED": "false"}),
            patch("dashboard.get_calendar", return_value=[]),
            patch("dashboard.task_state", return_value="Disabled"),
            patch("dashboard.sys.platform", "win32"),
            patch("dashboard.subprocess.CREATE_NEW_CONSOLE", 16, create=True),
            patch("dashboard.subprocess.Popen") as popen,
        ):
            page = app.test_client().get(
                "/?date=2026-10-14", headers={"Host": "127.0.0.1:8766"}
            )
            self.assertEqual(page.status_code, 200)
            self.assertEqual(page.headers["Referrer-Policy"], "same-origin")
            token = re.search(
                r'<form[^>]+action="/business-suite/start"[^>]*>.*?'
                r'<input[^>]+name="csrf"[^>]+value="([^"]+)"',
                page.get_data(as_text=True), re.S,
            )
            self.assertIsNotNone(token)
            accepted = app.test_client().post(
                "/business-suite/start",
                data={"csrf": token.group(1), "confirmation": "ABRIR",
                      "date": "2026-10-14", "browser": "existing"},
                headers={
                    "Host": "127.0.0.1:8766", "Origin": "null",
                    "Sec-Fetch-Site": "same-origin",
                },
            )
            self.assertEqual(accepted.status_code, 302)
            popen.assert_called_once()
            self.assertEqual(popen.call_args.args[0][-2:], ["--browser", "existing"])

    def test_business_suite_null_origin_from_cross_site_is_blocked(self):
        import os
        app = create_app(root=self.root)
        app.config["TESTING"] = True
        with (
            patch.dict(os.environ, {"ARAYFLOW_AUTOPUBLISH_ENABLED": "false"}),
            patch("dashboard.get_calendar", return_value=[]),
            patch("dashboard.task_state", return_value="Disabled"),
            patch("dashboard.subprocess.Popen") as popen,
        ):
            page = app.test_client().get(
                "/?date=2026-10-14", headers={"Host": "127.0.0.1:8766"}
            )
            token = re.search(
                r'<form[^>]+action="/business-suite/start"[^>]*>.*?'
                r'<input[^>]+name="csrf"[^>]+value="([^"]+)"',
                page.get_data(as_text=True), re.S,
            )
            self.assertIsNotNone(token)
            for fetch_site in ("cross-site", "", "same-site", "none"):
                rejected = app.test_client().post(
                    "/business-suite/start",
                    data={"csrf": token.group(1), "confirmation": "ABRIR",
                          "date": "2026-10-14"},
                    headers={
                        "Host": "127.0.0.1:8766", "Origin": "null",
                        "Sec-Fetch-Site": fetch_site,
                    },
                )
                self.assertEqual(rejected.status_code, 403)
            popen.assert_not_called()

    def test_dashboard_start_requires_csrf(self):
        app = create_app(root=self.root)
        app.config["TESTING"] = True
        response = app.test_client().post("/business-suite/start",
            data={"date": DAY, "confirmation": "ABRIR"},
            headers={"Host": "localhost"})
        self.assertEqual(response.status_code, 403)

    def test_dashboard_rejects_untrusted_host(self):
        app = create_app(root=self.root)
        app.config["TESTING"] = True
        response = app.test_client().get("/", headers={"Host": "example.invalid"})
        self.assertEqual(response.status_code, 400)

if __name__ == "__main__":
    unittest.main()
