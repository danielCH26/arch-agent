import json
import unittest
from unittest.mock import MagicMock, patch

from app.core.engram_client import EngramClient, EngramError


def make_response(payload: dict):
    response = MagicMock()
    response.read.return_value = json.dumps(payload).encode("utf-8")
    response.__enter__.return_value = response
    return response


class EngramClientTests(unittest.TestCase):
    @patch("app.core.engram_client.urlopen")
    def test_create_session_uses_engram_api(self, mock_urlopen):
        mock_urlopen.return_value = make_response({"id": "session-1"})
        client = EngramClient(base_url="http://engram.test")

        client.create_session("session-1", "arch-agent-user-1", "C:/workspace")

        request = mock_urlopen.call_args.args[0]
        self.assertEqual(request.full_url, "http://engram.test/sessions")
        self.assertEqual(request.method, "POST")
        self.assertEqual(
            json.loads(request.data),
            {"id": "session-1", "project": "arch-agent-user-1", "directory": "C:/workspace"},
        )

    @patch("app.core.engram_client.urlopen")
    def test_get_context_returns_context_text(self, mock_urlopen):
        mock_urlopen.return_value = make_response({"context": "La fase actual es descubrimiento."})

        context = EngramClient(base_url="http://engram.test").get_context("arch-agent-user-1")

        self.assertEqual(context, "La fase actual es descubrimiento.")
        self.assertIn("project=arch-agent-user-1", mock_urlopen.call_args.args[0].full_url)

    @patch("app.core.engram_client.urlopen", side_effect=OSError("servicio apagado"))
    def test_client_wraps_connection_errors(self, _mock_urlopen):
        with self.assertRaisesRegex(EngramError, "No fue posible conectar"):
            EngramClient(base_url="http://engram.test").get_context("arch-agent-user-1")
