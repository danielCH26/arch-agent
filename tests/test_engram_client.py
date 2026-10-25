import json
import unittest
from unittest.mock import MagicMock, patch

from app.core.engram_client import EngramClient, EngramError


def make_response(payload):
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


class EngramClientExtensionsTests(unittest.TestCase):
    """F12 REQ-5: search/get_observation/save(topic_key)/delete + REQ-5 ValueError."""

    @patch("app.core.engram_client.urlopen")
    def test_search_requires_project(self, _mock_urlopen):
        """SCN-6: search(project=None) MUST raise ValueError before hitting the wire."""
        client = EngramClient(base_url="http://engram.test")
        with self.assertRaisesRegex(ValueError, "project is required"):
            client.search(scope="project", query="auth", project=None, user_id=7)
        _mock_urlopen.assert_not_called()

    @patch("app.core.engram_client.urlopen")
    def test_search_requires_project_empty_string(self, _mock_urlopen):
        client = EngramClient(base_url="http://engram.test")
        with self.assertRaisesRegex(ValueError, "project is required"):
            client.search(scope="project", query="auth", project="", user_id=7)

    @patch("app.core.engram_client.urlopen")
    def test_search_scopes_by_project_and_user(self, mock_urlopen):
        mock_urlopen.return_value = make_response({"observations": [{"id": 11}]})
        client = EngramClient(base_url="http://engram.test")

        results = client.search(scope="project", query="auth", project="u-7-p-42", user_id=7)

        request = mock_urlopen.call_args.args[0]
        self.assertIn("project=u-7-p-42", request.full_url)
        self.assertIn("user_id=7", request.full_url)
        self.assertEqual(results, [{"id": 11}])

    @patch("app.core.engram_client.urlopen")
    def test_search_handles_list_payload(self, mock_urlopen):
        mock_urlopen.return_value = make_response([{"id": 1}, {"id": 2}])
        client = EngramClient(base_url="http://engram.test")

        results = client.search(scope="project", query="x", project="p1", user_id=1)
        self.assertEqual(results, [{"id": 1}, {"id": 2}])

    @patch("app.core.engram_client.urlopen")
    def test_get_observation_returns_dict(self, mock_urlopen):
        mock_urlopen.return_value = make_response({"id": 42, "content": "hi"})
        client = EngramClient(base_url="http://engram.test")

        result = client.get_observation(42)

        request = mock_urlopen.call_args.args[0]
        self.assertEqual(request.full_url, "http://engram.test/observations/42")
        self.assertEqual(result, {"id": 42, "content": "hi"})

    @patch("app.core.engram_client.urlopen")
    def test_save_sends_topic_key_and_content(self, mock_urlopen):
        mock_urlopen.return_value = make_response({"id": 99})
        client = EngramClient(base_url="http://engram.test")

        result = client.save(
            topic_key="arch-agent-user-7-project-42-chat",
            content="hola",
            title="user:1",
            observation_type="chat_message",
            project="u-7-p-42",
        )

        request = mock_urlopen.call_args.args[0]
        body = json.loads(request.data)
        self.assertEqual(request.full_url, "http://engram.test/observations")
        self.assertEqual(request.method, "POST")
        self.assertEqual(body["topic_key"], "arch-agent-user-7-project-42-chat")
        self.assertEqual(body["content"], "hola")
        self.assertEqual(body["scope"], "project")
        self.assertEqual(body["type"], "chat_message")
        self.assertEqual(result, {"id": 99})

    @patch("app.core.engram_client.urlopen")
    def test_save_without_project_omits_project_field(self, mock_urlopen):
        mock_urlopen.return_value = make_response({"id": 1})
        client = EngramClient(base_url="http://engram.test")

        client.save(topic_key="arch-agent-user-7", content="x")

        body = json.loads(mock_urlopen.call_args.args[0].data)
        self.assertNotIn("project", body)

    @patch("app.core.engram_client.urlopen")
    def test_delete_calls_delete_endpoint(self, mock_urlopen):
        mock_urlopen.return_value = make_response({"deleted": True})
        client = EngramClient(base_url="http://engram.test")

        client.delete(42)

        request = mock_urlopen.call_args.args[0]
        self.assertEqual(request.full_url, "http://engram.test/observations/42")
        self.assertEqual(request.method, "DELETE")
