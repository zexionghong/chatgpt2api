from __future__ import annotations

import email
import unittest
from datetime import datetime, timezone
from unittest import mock

from services.register import mail_provider


class FakeIMAP:
    messages: dict[bytes, bytes] = {}
    search_ids: list[bytes] = []
    exists_count: int = 0
    logged_in: tuple[str, str] | None = None
    fetched_ids: list[bytes] = []
    search_called: bool = False

    def __init__(self, host: str, port: int):
        self.host = host
        self.port = port
        self.selected = ""

    def login(self, username: str, password: str):
        self.__class__.logged_in = (username, password)
        return "OK", []

    def select(self, mailbox: str = "INBOX", readonly: bool = True):
        self.selected = mailbox
        count = self.__class__.exists_count or len(self.__class__.search_ids)
        return "OK", [str(count).encode("ascii")]

    def search(self, charset, *criteria):
        self.__class__.search_called = True
        return "OK", [b" ".join(self.__class__.search_ids)]

    def fetch(self, message_id: bytes, query: str):
        self.__class__.fetched_ids.append(message_id)
        return "OK", [(b"RFC822", self.__class__.messages[message_id])]

    def logout(self):
        return "OK", []


def make_message(*, to: str, date: str, code: str = "123456", message_id: str = "<m@example.test>") -> bytes:
    msg = email.message.EmailMessage()
    msg["From"] = "OpenAI <noreply@tm.openai.com>"
    msg["To"] = to
    msg["Date"] = date
    msg["Subject"] = "OpenAI verification code"
    msg["Message-ID"] = message_id
    msg.set_content(f"Your verification code is {code}")
    return msg.as_bytes()


class QQMailProviderTests(unittest.TestCase):
    def setUp(self):
        FakeIMAP.messages = {}
        FakeIMAP.search_ids = []
        FakeIMAP.exists_count = 0
        FakeIMAP.logged_in = None
        FakeIMAP.fetched_ids = []
        FakeIMAP.search_called = False

    def _provider(self):
        return mail_provider.QQMailProvider(
            {
                "provider_ref": "qq_mail#1",
                "domain": ["example.com"],
                "imap_host": "imap.qq.com",
                "imap_port": 993,
                "imap_username": "main@qq.com",
                "imap_password": "auth-code",
            },
            {
                "request_timeout": 30,
                "wait_timeout": 1,
                "wait_interval": 1,
                "user_agent": "test",
                "proxy": "",
            },
        )

    def test_create_mailbox_uses_random_prefix_and_configured_domain(self):
        provider = self._provider()
        with mock.patch.object(mail_provider, "_random_mailbox_name", return_value="abc123"):
            mailbox = provider.create_mailbox()

        self.assertEqual(mailbox["provider"], "qq_mail")
        self.assertEqual(mailbox["address"], "abc123@example.com")
        self.assertIsInstance(mailbox["created_at"], str)

    def test_fetch_latest_message_matches_recipient_and_created_time(self):
        provider = self._provider()
        FakeIMAP.search_ids = [b"1", b"2", b"3"]
        FakeIMAP.messages = {
            b"1": make_message(
                to="target@example.com",
                date="Thu, 04 Jun 2026 11:59:00 +0000",
                code="111111",
                message_id="<old@example.test>",
            ),
            b"2": make_message(
                to="other@example.com",
                date="Thu, 04 Jun 2026 12:02:00 +0000",
                code="222222",
                message_id="<other@example.test>",
            ),
            b"3": make_message(
                to="target@example.com",
                date="Thu, 04 Jun 2026 12:03:00 +0000",
                code="333333",
                message_id="<target@example.test>",
            ),
        }
        mailbox = {
            "address": "target@example.com",
            "created_at": datetime(2026, 6, 4, 12, 0, 0, tzinfo=timezone.utc).isoformat(),
        }

        with mock.patch("services.register.mail_provider.imaplib.IMAP4_SSL", FakeIMAP):
            message = provider.fetch_latest_message(mailbox)

        self.assertIsNotNone(message)
        self.assertEqual(message["message_id"], "<target@example.test>")
        self.assertIn("333333", message["text_content"])
        self.assertEqual(FakeIMAP.logged_in, ("main@qq.com", "auth-code"))

    def test_fetch_latest_message_checks_only_recent_five_messages(self):
        provider = self._provider()
        FakeIMAP.exists_count = 7
        FakeIMAP.messages = {
            str(index).encode("ascii"): make_message(
                to="other@example.com",
                date="Thu, 04 Jun 2026 12:03:00 +0000",
                message_id=f"<{index}@example.test>",
            )
            for index in range(1, 8)
        }
        mailbox = {
            "address": "target@example.com",
            "created_at": datetime(2026, 6, 4, 12, 0, 0, tzinfo=timezone.utc).isoformat(),
        }

        with mock.patch("services.register.mail_provider.imaplib.IMAP4_SSL", FakeIMAP):
            message = provider.fetch_latest_message(mailbox)

        self.assertIsNone(message)
        self.assertEqual(FakeIMAP.fetched_ids, [b"7", b"6", b"5", b"4", b"3"])
        self.assertFalse(FakeIMAP.search_called)

    def test_wait_for_code_retries_three_times_every_twenty_seconds(self):
        provider = self._provider()
        mailbox = {
            "address": "target@example.com",
            "created_at": datetime(2026, 6, 4, 12, 0, 0, tzinfo=timezone.utc).isoformat(),
        }

        with (
            mock.patch.object(provider, "fetch_latest_message", return_value=None) as fetch_mock,
            mock.patch("services.register.mail_provider.time.sleep") as sleep_mock,
        ):
            code = provider.wait_for_code(mailbox)

        self.assertIsNone(code)
        self.assertEqual(fetch_mock.call_count, 3)
        self.assertEqual([call.args[0] for call in sleep_mock.call_args_list], [20, 20])


if __name__ == "__main__":
    unittest.main()
