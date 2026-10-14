"""Testes offline do armazenamento R2, sem chamadas de rede."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from r2_storage import R2Storage

ENV = {
    "R2_ACCOUNT_ID":"test-account",
    "R2_ACCESS_KEY_ID":"test-access",
    "R2_SECRET_ACCESS_KEY":"test-secret",
    "R2_BUCKET_NAME":"arayflow-media",
    "R2_PUBLIC_URL":"https://pub-example.r2.dev",
}

class FakeS3:
    def __init__(self):
        self.uploads = []
        self.deleted = []
    def head_bucket(self, **kwargs):
        return {"ResponseMetadata":{"HTTPStatusCode":200}}
    def upload_file(self, filename, bucket, key, ExtraArgs=None):
        self.uploads.append((filename,bucket,key,ExtraArgs))
    def head_object(self, **kwargs):
        return {"ContentLength":100}
    def delete_object(self, **kwargs):
        self.deleted.append(kwargs)

class R2Tests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, ENV)
        self.env.start()
        self.s3 = FakeS3()
        self.r2 = R2Storage(client=self.s3)
    def tearDown(self):
        self.env.stop()

    def test_url_and_key(self):
        key = self.r2.key_for("ARAY-20261014-001",
                               Path("ARAY-20261014-001_slide-01.png"))
        self.assertEqual(key, "arayflow/2026-10-14/ARAY-20261014-001/ARAY-20261014-001_slide-01.png")
        self.assertEqual(self.r2.url_for(key),
            "https://pub-example.r2.dev/"+key)

    def test_upload_content_type(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "ARAY-20261014-001_slide-01.png"
            path.write_bytes(b"fake image bytes: API mocked")
            key, _ = self.r2.upload("ARAY-20261014-001",path)
            self.assertEqual(len(self.s3.uploads),1)
            self.assertEqual(self.s3.uploads[0][3]["ContentType"],"image/png")
            self.assertTrue(key.endswith("slide-01.png"))

    def test_restrict_deletion(self):
        with self.assertRaises(ValueError):
            self.r2.delete("outro-bucket/segredo")
        self.assertEqual(self.s3.deleted, [])

if __name__ == "__main__":
    unittest.main()
