"""Testes offline do agendamento. Nunca chamam Google, R2 ou Meta reais."""
import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock, patch

from scheduled_publish import ZONE, decision, scheduled_time, run_once, safe_cleanup
from publication_store import PublicationStore
from sync_store import SyncStore

POST = {
    "ID": "ARAY-20261014-001",
    "Data": "14/10/2026",
    "Horário": "07:00",
    "Status": "Aprovado",
    "Qtd. imagens": "3",
    "Legenda pronta": "Legenda de teste"
}
OLD_KEY = "arayflow/2026-10-13/ARAY-20261013-001/ARAY-20261013-001_slide-01.png"

class Clock(datetime):
    fixed = datetime(2026, 10, 14, 7, 0, tzinfo=ZONE)
    @classmethod
    def now(cls, tz=None):
        return cls.fixed.astimezone(tz or ZONE)
    @classmethod
    def strptime(cls, value, fmt):
        return datetime.strptime(value, fmt)

class SchedulerTests(unittest.TestCase):
    def stamp(self, hour, minute):
        return datetime(2026, 10, 14, hour, minute, tzinfo=ZONE)

    def test_parse_schedule(self):
        self.assertEqual(scheduled_time(POST), self.stamp(7,0))

    def test_time_windows(self):
        self.assertEqual(decision(POST, self.stamp(6,45)), "WAIT")
        self.assertEqual(decision(POST, self.stamp(6,50)), "PREPARE")
        self.assertEqual(decision(POST, self.stamp(7,0)), "DUE")
        self.assertEqual(decision(POST, self.stamp(7,14)), "DUE")
        self.assertEqual(decision(POST, self.stamp(7,16)), "EXPIRED")

    def test_not_approved_is_never_due(self):
        post = {**POST, "Status": "Pronto para revisão"}
        self.assertEqual(decision(post, self.stamp(7,0)), "SKIP")

    def test_invalid_time_blocks(self):
        post = {**POST, "Horário": "25:30"}
        with self.assertRaises(ValueError):
            decision(post, self.stamp(7,0))

    def test_dry_run_no_network_writes(self):
        with patch("scheduled_publish.rows_today", return_value=[POST]):
            self.assertEqual(run_once(False, self.stamp(6,55), sheets=object()), 0)

    def test_no_duplicate_after_published(self):
        store = Mock()
        store.get.return_value = ("published", "media", "container")
        publisher = Mock()
        with patch.dict(os.environ, {"ARAYFLOW_AUTOPUBLISH_ENABLED":"true"}), \
             patch("scheduled_publish.rows_today", return_value=[POST]):
            self.assertEqual(run_once(True, self.stamp(7,0), sheets=object(),
                drive=object(), store=store, sessions=Mock(),
                storage=Mock(), publisher=publisher), 0)
        publisher.prepare.assert_not_called()
        publisher.publish.assert_not_called()

    def test_prepared_publishes_one_time_with_atomic_claim(self):
        store = Mock()
        store.get.return_value = ("prepared", None, "container123")
        store.transition.return_value = True
        publisher = Mock()
        publisher.publish.return_value = "media456"
        with patch.dict(os.environ, {"ARAYFLOW_AUTOPUBLISH_ENABLED":"true"}), \
             patch("scheduled_publish.rows_today", return_value=[POST]), \
             patch("scheduled_publish.datetime", Clock):
            self.assertEqual(run_once(True, self.stamp(7,0), sheets=object(),
                drive=object(), store=store, sessions=Mock(),
                storage=Mock(), publisher=publisher), 0)
        publisher.wait.assert_called_once_with("container123", attempts=1, interval=0)
        publisher.publish.assert_called_once_with("container123")
        store.transition.assert_any_call("ARAY-20261014-001", "prepared", "publishing")
        store.transition.assert_any_call("ARAY-20261014-001", "publishing", "published", media_id="media456")

    def test_opt_in_required(self):
        with patch.dict(os.environ, {"ARAYFLOW_AUTOPUBLISH_ENABLED":"false"}), \
             patch("scheduled_publish.rows_today", return_value=[POST]):
            with self.assertRaises(RuntimeError):
                run_once(True, self.stamp(7,0), sheets=object())

    def test_session_atomic_claim_and_resume(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "session.sqlite3"
            store = PublicationStore(path)
            self.assertTrue(store.claim("ARAY-20261014-001"))
            self.assertFalse(store.claim("ARAY-20261014-001"))
            self.assertTrue(store.transition("ARAY-20261014-001","preparing","prepared",container_id="cid"))
            self.assertFalse(store.transition("ARAY-20261014-001","preparing","prepared"))
            store.close()
            store = PublicationStore(path)
            self.assertEqual(store.get("ARAY-20261014-001"), ("prepared",None,"cid"))
            store.close()

    def test_cleanup_only_old_unprotected_images(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "session.sqlite3"
            store = PublicationStore(path)
            sessions = SyncStore(path)
            store.claim("ARAY-20261013-001")
            storage = Mock()
            other = "arayflow/2026-10-12/ARAY-20261012-001/ARAY-20261012-001_slide-01.png"
            today = "arayflow/2026-10-14/ARAY-20261014-001/ARAY-20261014-001_slide-01.png"
            storage.list_managed.return_value = [OLD_KEY, other, today]
            count = safe_cleanup(storage, sessions, "2026-10-14")
            self.assertEqual(count, 1)
            storage.delete.assert_called_once_with(other)
            store.close()
            sessions.close()

if __name__ == "__main__":
    unittest.main()
