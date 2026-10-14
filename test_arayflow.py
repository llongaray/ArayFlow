"""Testes offline: nao acessam Google nem Meta."""
import tempfile
import unittest
from pathlib import Path
from PIL import Image
from image_validator import inspect_image, validate_batch
from publication_store import PublicationStore
from arayflow.local_media import require_slide_sequence

class ImageValidatorTests(unittest.TestCase):
    def test_valid_png(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "slide.png"
            Image.new("RGB",(1080,1350)).save(path)
            report = inspect_image(path)
            self.assertEqual((report.width,report.height),(1080,1350))
            self.assertEqual(len(validate_batch([path])),1)

    def test_slide_sequence_requires_continuous_numbers(self):
        post = "ARAY-20261014-001"
        complete = [Path(f"{post}_slide-0{n}.png") for n in (1, 2, 3)]
        require_slide_sequence(complete, 3, post)
        gapped = [Path(f"{post}_slide-01.png"), Path(f"{post}_slide-03.png")]
        with self.assertRaisesRegex(ValueError, "continuos"):
            require_slide_sequence(gapped, 2, post)

    def test_invalid_ratio(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "tall.png"
            Image.new("RGB",(200,1000)).save(path)
            with self.assertRaises(ValueError):
                inspect_image(path)

    def test_corrupt_file(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "broken.png"
            path.write_bytes(b"not an image")
            with self.assertRaises(ValueError):
                inspect_image(path)

class PublicationStoreTests(unittest.TestCase):
    def test_state_survives_reopen(self):
        with tempfile.TemporaryDirectory() as temp:
            db_path = Path(temp) / "status.db"
            store = PublicationStore(db_path)
            store.set("TEST-001","prepared",container_id="123")
            store.close()
            store = PublicationStore(db_path)
            self.assertEqual(store.get("TEST-001"),("prepared",None,"123"))
            store.set("TEST-001","published",media_id="456")
            self.assertEqual(store.get("TEST-001"),("published","456","123"))
            store.close()

if __name__ == "__main__":
    unittest.main()
