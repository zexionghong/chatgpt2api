from __future__ import annotations

import unittest
from unittest import mock

from services.register import openai_register


class RegisterFlowTests(unittest.TestCase):
    def test_waits_five_seconds_after_sending_otp_before_polling_mail(self):
        events: list[str] = []

        class FakeRegistrar(openai_register.PlatformRegistrar):
            def __init__(self):
                self.device_id = "device"
                self.code_verifier = ""
                self.platform_auth_code = ""

            def _platform_authorize(self, email: str, index: int) -> None:
                events.append("authorize")

            def _register_user(self, email: str, password: str, index: int) -> None:
                events.append("register_user")

            def _send_otp(self, index: int) -> None:
                events.append("send_otp")

            def _validate_otp(self, code: str, index: int) -> None:
                events.append("validate_otp")

            def _create_account(self, name: str, birthdate: str, index: int) -> None:
                events.append("create_account")

            def _exchange_registered_tokens(self, index: int) -> dict:
                events.append("exchange_tokens")
                return {"access_token": "access", "refresh_token": "refresh", "id_token": "id"}

        def fake_sleep(seconds: float) -> None:
            events.append(f"sleep:{seconds:g}")

        def fake_wait_for_code(mailbox: dict) -> str:
            events.append("wait_for_code")
            return "123456"

        with (
            mock.patch.object(openai_register, "create_mailbox", return_value={"address": "test@example.com"}),
            mock.patch.object(openai_register, "wait_for_code", side_effect=fake_wait_for_code),
            mock.patch.object(openai_register, "_random_password", return_value="Password1!"),
            mock.patch.object(openai_register, "_random_name", return_value=("First", "Last")),
            mock.patch.object(openai_register, "_random_birthdate", return_value="2000-01-01"),
            mock.patch.object(openai_register.time, "sleep", side_effect=fake_sleep),
        ):
            FakeRegistrar().register(1)

        self.assertLess(events.index("send_otp"), events.index("sleep:5"))
        self.assertLess(events.index("sleep:5"), events.index("wait_for_code"))


if __name__ == "__main__":
    unittest.main()
