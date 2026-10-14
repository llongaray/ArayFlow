"""Testes de seguranca e retomada da sincronizacao diaria R2, sem rede."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from r2_storage import R2Storage
from sync_store import SyncStore
from publication_store import PublicationStore
from sync_day import sha256_file, classify, make_plan, execute_plan

ENV = {
    "R2_ACCOUNT_ID": "fake",
    "R2_ACCESS_KEY_ID": "fake",
    "R2_SECRET_ACCESS_KEY": "fake",
    "R2_BUCKET_NAME": "arayflow-media",
    "R2_PUBLIC_URL": "https://pub-example.r2.dev",
}

class FakeS3:
    def __init__(self):
        self.objects = {}
        self.deleted = []
        self.uploaded = []
        self.fail_once = False
    def list_objects_v2(self, **kwargs):
        keys = sorted(k for k in self.objects if k.startswith(kwargs["Prefix"]))
        start = int(kwargs.get("ContinuationToken", "0"))
        batch = keys[start:start+1000]
        end = start + len(batch)
        return {"Contents": [{"Key": k} for k in batch],
                "IsTruncated": end < len(keys),
                "NextContinuationToken": str(end) if end < len(keys) else None}
    def head_object(self, **kwargs):
        return {"Metadata": self.objects[kwargs["Key"]], "ContentLength": 12}
    def upload_file(self, filename, bucket, key, ExtraArgs=None):
        if self.fail_once:
            self.fail_once = False
            raise RuntimeError("falha de rede simulada")
        self.objects[key] = (ExtraArgs or {}).get("Metadata", {})
        self.uploaded.append(key)
    def delete_object(self, **kwargs):
        self.objects.pop(kwargs["Key"], None)
        self.deleted.append(kwargs["Key"])

class SyncTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, ENV)
        self.env.start()
        self.fake = FakeS3()
        self.r2 = R2Storage(client=self.fake)
        self.store = SyncStore(Path(self.tmp.name) / "data" / "arayflow.sqlite3")
        self.day = "2026-10-15"
        self.post_id = "ARAY-20261015-001"
        self.path = Path(self.tmp.name) / (self.post_id + "_slide-01.png")
        Image.new("RGB", (1080, 1350)).save(self.path)
        self.asset = {
            "post_id": self.post_id, "path": self.path,
            "key": self.r2.key_for(self.post_id, self.path),
            "sha256": sha256_file(self.path)
        }
        self.asset["url"] = self.r2.url_for(self.asset["key"])
    def tearDown(self):
        self.store.close()
        self.env.stop()
        self.tmp.cleanup()

    def test_delete_old_but_keep_outside_prefix(self):
        old = "arayflow/2026-10-14/ARAY-20261014-001/ARAY-20261014-001_slide-01.png"
        other = "client-data/secret.png"
        self.fake.objects[old] = {}
        self.fake.objects[other] = {}
        self.assertEqual(self.r2.list_managed(), [old])
        plan = make_plan(self.r2, self.store, self.day, [self.asset])
        self.assertEqual(plan["delete"], [old])
        with patch("sync_day.BASE_DIR", Path(self.tmp.name)):
            execute_plan(self.day, [self.asset], plan, self.r2, self.store)
        self.assertNotIn(old, self.fake.objects)
        self.assertIn(other, self.fake.objects)
        self.assertIn(self.asset["key"], self.fake.objects)
        self.assertEqual(self.store.get_sessions()[0][1], "complete")
        self.assertTrue((Path(self.tmp.name) / "data" / (self.post_id + "-r2-urls.json")).exists())

    def test_protect_prepared_meta_post(self):
        old_post = "ARAY-20261014-001"
        old = self.r2.key_for(old_post, Path(old_post + "_slide-01.png"))
        self.fake.objects[old] = {}
        publication = PublicationStore(Path(self.tmp.name) / "data" / "arayflow.sqlite3")
        publication.set(old_post, "prepared", container_id="111")
        publication.close()
        plan = make_plan(self.r2, self.store, self.day, [self.asset])
        self.assertEqual(plan["delete"], [])
        self.assertEqual(plan["protected"], [old])

    def test_protect_incomplete_session(self):
        self.store.begin("2026-10-14")
        old = "arayflow/2026-10-14/ARAY-20261014-001/ARAY-20261014-001_slide-01.png"
        self.fake.objects[old] = {}
        plan = make_plan(self.r2, self.store, self.day, [self.asset])
        self.assertEqual(plan["protected"], [old])

    def test_retry_reuses_hashed_object(self):
        with patch("sync_day.BASE_DIR", Path(self.tmp.name)):
            first = make_plan(self.r2, self.store, self.day, [self.asset])
            execute_plan(self.day, [self.asset], first, self.r2, self.store)
            self.assertEqual(len(self.fake.uploaded), 1)
            second = make_plan(self.r2, self.store, self.day, [self.asset])
            self.assertEqual(len(second["reuse"]), 1)
            execute_plan(self.day, [self.asset], second, self.r2, self.store)
            self.assertEqual(len(self.fake.uploaded), 1)

    def test_failure_is_saved_then_resumed(self):
        self.fake.fail_once = True
        with patch("sync_day.BASE_DIR", Path(self.tmp.name)):
            plan = make_plan(self.r2, self.store, self.day, [self.asset])
            with self.assertRaises(RuntimeError):
                execute_plan(self.day, [self.asset], plan, self.r2, self.store)
            self.assertEqual(self.store.get_sessions()[0][1], "failed")
            execute_plan(self.day, [self.asset], plan, self.r2, self.store)
        self.assertEqual(self.store.get_sessions()[0][1], "complete")

    def test_pagination_and_no_other_keys(self):
        for n in range(1, 1003):
            pid = f"ARAY-20261014-{n:04d}"
            key = self.r2.key_for(pid, Path(f"{pid}_slide-01.png"))
            self.fake.objects[key] = {}
        self.fake.objects["something-else/private.txt"] = {}
        self.assertEqual(len(self.r2.list_managed()), 1002)

    def test_protect_declared_posts(self):
        old = "arayflow/2026-10-14/ARAY-20261014-001/ARAY-20261014-001_slide-01.png"
        removable, protected = classify(
            [old], {self.asset["key"]}, {"ARAY-20261014-001"}, set(), self.day,
        )
        self.assertEqual(removable, [])
        self.assertEqual(protected, [old])

    def test_future_day_is_not_deleted(self):
        future = "arayflow/2026-10-16/ARAY-20261016-001/ARAY-20261016-001_slide-01.png"
        past = "arayflow/2026-10-14/ARAY-20261014-009/ARAY-20261014-009_slide-01.png"
        self.fake.objects[future] = {}
        self.fake.objects[past] = {}
        plan = make_plan(self.r2, self.store, self.day, [self.asset])
        self.assertIn(future, plan["protected"])
        self.assertNotIn(future, plan["delete"])
        self.assertIn(past, plan["delete"])

if __name__ == "__main__":
    unittest.main()
