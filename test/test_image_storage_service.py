from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image

from services.image_storage_service import ImageStorageService


def png_bytes() -> bytes:
    path = Path(tempfile.gettempdir()) / "chatgpt2api-test-image.png"
    Image.new("RGB", (2, 2), color=(255, 0, 0)).save(path, format="PNG")
    return path.read_bytes()


class FakeWebDAVClient:
    uploaded: dict[str, bytes] = {}
    deleted: list[str] = []

    def __init__(self, _settings):
        pass

    def put(self, rel: str, payload: bytes) -> str:
        self.uploaded[rel] = payload
        return f"https://dav.example.test/{rel}"

    def get(self, rel: str) -> bytes:
        return self.uploaded[rel]

    def delete(self, rel: str) -> bool:
        self.deleted.append(rel)
        self.uploaded.pop(rel, None)
        return True

    def test(self) -> dict[str, object]:
        self.put(".chatgpt2api_webdav_test.txt", b"chatgpt2api webdav test\n")
        self.delete(".chatgpt2api_webdav_test.txt")
        return {"ok": True, "status": 200, "error": None}


class FakeS3Client:
    uploaded: dict[str, bytes] = {}
    deleted: list[str] = []

    def __init__(self, _settings):
        pass

    def put(self, rel: str, payload: bytes, content_type: str = "image/png") -> str:
        self.uploaded[rel] = payload
        return f"https://bucket.oss.example.test/{rel}"

    def get(self, rel: str) -> bytes:
        return self.uploaded[rel]

    def delete(self, rel: str) -> bool:
        self.deleted.append(rel)
        self.uploaded.pop(rel, None)
        return True

    def test(self) -> dict[str, object]:
        self.put(".chatgpt2api_s3_test.txt", b"chatgpt2api s3 test\n", content_type="text/plain")
        self.delete(".chatgpt2api_s3_test.txt")
        return {"ok": True, "status": 200, "error": None}


class ImageStorageServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.data_dir = Path(self.tmp.name)
        self.images_dir = self.data_dir / "images"
        self.settings = {
            "enabled": False,
            "mode": "local",
            "webdav_url": "",
            "webdav_username": "",
            "webdav_password": "",
            "webdav_root_path": "chatgpt2api/images",
            "s3_endpoint": "",
            "s3_region": "auto",
            "s3_bucket": "",
            "s3_access_key_id": "",
            "s3_secret_access_key": "",
            "s3_prefix": "chatgpt2api/images",
            "s3_force_path_style": True,
            "public_base_url": "",
        }
        self.config_patcher = mock.patch("services.image_storage_service.config")
        self.mock_config = self.config_patcher.start()
        self.addCleanup(self.config_patcher.stop)
        self.mock_config.images_dir = self.images_dir
        self.mock_config.base_url = "http://app.test"
        self.mock_config.cleanup_old_images.return_value = 0
        self.mock_config.get_image_storage_settings.side_effect = lambda: dict(self.settings)
        FakeWebDAVClient.uploaded = {}
        FakeWebDAVClient.deleted = []
        FakeS3Client.uploaded = {}
        FakeS3Client.deleted = []

    def service(self) -> ImageStorageService:
        return ImageStorageService(self.data_dir / "image_index.json")

    def test_local_mode_saves_to_local_directory(self):
        stored = self.service().save(png_bytes(), "http://app.test")

        self.assertEqual(stored.storage, "local")
        self.assertTrue((self.images_dir / stored.rel).is_file())
        self.assertEqual(stored.url, f"http://app.test/images/{stored.rel}")

    def test_webdav_mode_uploads_without_local_file(self):
        self.settings.update({
            "enabled": True,
            "mode": "webdav",
            "webdav_url": "https://dav.example.test",
            "webdav_password": "secret",
        })
        with mock.patch("services.image_storage_service.WebDAVClient", FakeWebDAVClient):
            stored = self.service().save(png_bytes(), "http://app.test")
            payload = self.service().get_bytes(stored.rel)

        self.assertEqual(stored.storage, "webdav")
        self.assertFalse((self.images_dir / stored.rel).exists())
        self.assertIn(stored.rel, FakeWebDAVClient.uploaded)
        self.assertEqual(payload, FakeWebDAVClient.uploaded[stored.rel])

    def test_list_items_ignores_non_image_files(self):
        image = png_bytes()
        image_path = self.images_dir / "2026" / "05" / "07" / "sample.png"
        image_path.parent.mkdir(parents=True, exist_ok=True)
        image_path.write_bytes(image)
        (self.images_dir / ".DS_Store").write_text("not an image", encoding="utf-8")
        (self.images_dir / "2026" / ".DS_Store").write_text("not an image", encoding="utf-8")

        items = self.service().list_items("http://app.test")

        self.assertEqual([item["rel"] for item in items], ["2026/05/07/sample.png"])
        self.assertEqual(items[0]["storage"], "local")

    def test_both_mode_saves_to_local_and_webdav(self):
        self.settings.update({
            "enabled": True,
            "mode": "both",
            "webdav_url": "https://dav.example.test",
            "webdav_password": "secret",
            "public_base_url": "https://cdn.example.test/images",
        })
        with mock.patch("services.image_storage_service.WebDAVClient", FakeWebDAVClient):
            stored = self.service().save(png_bytes(), "http://app.test")

        self.assertEqual(stored.storage, "both")
        self.assertTrue((self.images_dir / stored.rel).is_file())
        self.assertIn(stored.rel, FakeWebDAVClient.uploaded)
        self.assertEqual(stored.url, f"https://cdn.example.test/images/{stored.rel}")

    def test_test_webdav_writes_and_deletes_probe_file(self):
        self.settings.update({
            "enabled": True,
            "mode": "webdav",
            "webdav_url": "https://dav.example.test",
            "webdav_password": "secret",
        })
        with mock.patch("services.image_storage_service.WebDAVClient", FakeWebDAVClient):
            result = self.service().test_webdav()

        self.assertTrue(result["ok"])
        self.assertIn(".chatgpt2api_webdav_test.txt", FakeWebDAVClient.deleted)

    def test_s3_mode_uploads_without_local_file(self):
        self.settings.update({
            "enabled": True,
            "mode": "s3",
            "s3_endpoint": "https://oss.example.test",
            "s3_region": "cn-hangzhou",
            "s3_bucket": "bucket",
            "s3_access_key_id": "ak",
            "s3_secret_access_key": "sk",
            "s3_prefix": "chatgpt2api/images",
            "public_base_url": "https://cdn.example.test",
        })
        with mock.patch("services.image_storage_service.S3Client", FakeS3Client):
            stored = self.service().save(png_bytes(), "http://app.test")
            payload = self.service().get_bytes(stored.rel)

        self.assertEqual(stored.storage, "s3")
        self.assertFalse((self.images_dir / stored.rel).exists())
        self.assertIn(stored.rel, FakeS3Client.uploaded)
        self.assertEqual(payload, FakeS3Client.uploaded[stored.rel])
        self.assertEqual(stored.url, f"https://cdn.example.test/chatgpt2api/images/{stored.rel}")

    def test_s3_both_mode_saves_to_local_and_s3(self):
        self.settings.update({
            "enabled": True,
            "mode": "s3_both",
            "s3_endpoint": "https://oss.example.test",
            "s3_region": "cn-hangzhou",
            "s3_bucket": "bucket",
            "s3_access_key_id": "ak",
            "s3_secret_access_key": "sk",
        })
        with mock.patch("services.image_storage_service.S3Client", FakeS3Client):
            stored = self.service().save(png_bytes(), "http://app.test")

        self.assertEqual(stored.storage, "s3_both")
        self.assertTrue((self.images_dir / stored.rel).is_file())
        self.assertIn(stored.rel, FakeS3Client.uploaded)

    def test_delete_removes_s3_object(self):
        self.settings.update({
            "enabled": True,
            "mode": "s3",
            "s3_endpoint": "https://oss.example.test",
            "s3_region": "cn-hangzhou",
            "s3_bucket": "bucket",
            "s3_access_key_id": "ak",
            "s3_secret_access_key": "sk",
        })
        with mock.patch("services.image_storage_service.S3Client", FakeS3Client):
            stored = self.service().save(png_bytes(), "http://app.test")
            removed = self.service().delete(stored.rel)

        self.assertTrue(removed)
        self.assertIn(stored.rel, FakeS3Client.deleted)

    def test_test_storage_uses_s3_probe_for_s3_mode(self):
        self.settings.update({
            "enabled": True,
            "mode": "s3",
            "s3_endpoint": "https://oss.example.test",
            "s3_region": "cn-hangzhou",
            "s3_bucket": "bucket",
            "s3_access_key_id": "ak",
            "s3_secret_access_key": "sk",
        })
        with mock.patch("services.image_storage_service.S3Client", FakeS3Client):
            result = self.service().test_connection()

        self.assertTrue(result["ok"])
        self.assertIn(".chatgpt2api_s3_test.txt", FakeS3Client.deleted)


if __name__ == "__main__":
    unittest.main()
