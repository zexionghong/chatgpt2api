from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from services.log_service import LOG_TYPE_CALL, LogService, LoggedCall


class LoggedCallTests(unittest.TestCase):
    def test_image_call_summary_includes_duration(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            temp_log_service = LogService(Path(tmp_dir) / "logs.jsonl")
            call = LoggedCall(
                {"id": "key-1", "name": "admin", "role": "admin"},
                "/v1/images/generations",
                "gpt-image-2",
                "文生图",
                started=100.0,
            )

            with mock.patch("services.log_service.log_service", temp_log_service), mock.patch("services.log_service.time.time", return_value=102.0):
                call.log("调用完成", {"data": [{"url": "https://example.test/image.png"}]})

            items = temp_log_service.list(type=LOG_TYPE_CALL)

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["summary"], "文生图调用完成，耗时 2.00s")
        self.assertEqual(items[0]["detail"]["duration_ms"], 2000)


if __name__ == "__main__":
    unittest.main()
