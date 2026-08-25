"""
Tests para el validador de LLM.

Issue: #7 - HU12 Configuración de LLM
"""

import pytest
import httpx
from unittest.mock import MagicMock, patch

from app.core.llm_validator import (
    validate_llm_config,
    get_available_models,
    LLMValidationError,
)


class TestValidateLLMConfig:
    """Tests de validate_llm_config."""

    def test_valid_config_returns_true(self):
        """Config válida → True."""
        mock_response = MagicMock()
        mock_response.status_code = 200

        with patch("app.core.llm_validator.httpx.get", return_value=mock_response):
            assert validate_llm_config("https://api.openai.com/v1", "sk-test") is True

    def test_401_raises_with_specific_message(self):
        mock_response = MagicMock()
        mock_response.status_code = 401

        with patch("app.core.llm_validator.httpx.get", return_value=mock_response):
            with pytest.raises(LLMValidationError, match="API Key inválida"):
                validate_llm_config("https://api.openai.com/v1", "bad-key")

    def test_404_raises_with_specific_message(self):
        mock_response = MagicMock()
        mock_response.status_code = 404

        with patch("app.core.llm_validator.httpx.get", return_value=mock_response):
            with pytest.raises(LLMValidationError, match="no existe"):
                validate_llm_config("https://wrong-url.com/v1", "sk-test")

    def test_500_raises_with_status_code(self):
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"

        with patch("app.core.llm_validator.httpx.get", return_value=mock_response):
            with pytest.raises(LLMValidationError) as exc_info:
                validate_llm_config("https://api.openai.com/v1", "sk-test")
            assert exc_info.value.status_code == 500

    def test_timeout_raises_with_specific_message(self):
        with patch(
            "app.core.llm_validator.httpx.get",
            side_effect=httpx.TimeoutException("timeout"),
        ):
            with pytest.raises(LLMValidationError, match="no respondió"):
                validate_llm_config("https://api.openai.com/v1", "sk-test")

    def test_connection_error_raises(self):
        with patch(
            "app.core.llm_validator.httpx.get",
            side_effect=httpx.ConnectError("connection refused"),
        ):
            with pytest.raises(LLMValidationError, match="No se pudo conectar"):
                validate_llm_config("https://api.openai.com/v1", "sk-test")

    def test_empty_base_url_raises(self):
        with pytest.raises(LLMValidationError, match="obligatorios"):
            validate_llm_config("", "sk-test")

    def test_empty_api_key_raises(self):
        with pytest.raises(LLMValidationError, match="obligatorios"):
            validate_llm_config("https://api.openai.com/v1", "")

    def test_trailing_slash_is_normalized(self):
        """URLs con / final deben funcionar igual que sin él."""
        mock_response = MagicMock()
        mock_response.status_code = 200

        with patch("app.core.llm_validator.httpx.get", return_value=mock_response) as mock_get:
            validate_llm_config("https://api.openai.com/v1/", "sk-test")
            # Verificar que se llamó sin slash final
            called_url = mock_get.call_args[0][0]
            assert called_url == "https://api.openai.com/v1/models"


class TestGetAvailableModels:
    """Tests de get_available_models."""

    def test_returns_list_of_model_ids(self):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": [
                {"id": "gpt-4o"},
                {"id": "gpt-4o-mini"},
                {"id": "gpt-3.5-turbo"},
            ]
        }

        with patch("app.core.llm_validator.httpx.get", return_value=mock_response):
            models = get_available_models(
                "https://api.openai.com/v1", "sk-test", user_id=1, engram_client=None
            )
            assert models == ["gpt-4o", "gpt-4o-mini", "gpt-3.5-turbo"]

    def test_empty_models_response(self):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"data": []}

        with patch("app.core.llm_validator.httpx.get", return_value=mock_response):
            models = get_available_models(
                "https://api.openai.com/v1", "sk-test", user_id=1, engram_client=None
            )
            assert models == []

    def test_timeout_raises(self):
        with patch(
            "app.core.llm_validator.httpx.get",
            side_effect=httpx.TimeoutException("timeout"),
        ):
            with pytest.raises(LLMValidationError, match="Timeout"):
                get_available_models(
                    "https://api.openai.com/v1", "sk-test", user_id=1, engram_client=None
                )

    def test_force_refresh_bypasses_cache(self):
        """Con force_refresh=True, debe llamar a la API aunque haya cache."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"data": [{"id": "model-1"}]}

        # Engram client mock que devolvería cache si se consultara
        mock_engram = MagicMock()
        mock_engram.search.return_value = [{"id": "obs-1"}]
        mock_engram.get_observation.return_value = {
            "models": ["cached-model"],
            "fetched_at": "2099-01-01T00:00:00",  # futuro, no expirado
        }

        with patch("app.core.llm_validator.httpx.get", return_value=mock_response):
            models = get_available_models(
                "https://api.openai.com/v1",
                "sk-test",
                user_id=1,
                engram_client=mock_engram,
                force_refresh=True,  # ignora cache
            )
            assert models == ["model-1"]  # vino de la API, no del cache

    def test_cache_hit_returns_cached_models(self):
        """Si hay cache vigente, debe devolverlo sin llamar a la API."""
        mock_engram = MagicMock()
        mock_engram.search.return_value = [{"id": "obs-1"}]
        mock_engram.get_observation.return_value = {
            "models": ["cached-model-1", "cached-model-2"],
            "fetched_at": "2099-01-01T00:00:00",  # futuro
        }

        with patch("app.core.llm_validator.httpx.get") as mock_get:
            models = get_available_models(
                "https://api.openai.com/v1",
                "sk-test",
                user_id=1,
                engram_client=mock_engram,
            )
            assert models == ["cached-model-1", "cached-model-2"]
            mock_get.assert_not_called()  # No llamó a la API

    def test_cache_expired_calls_api(self):
        """Si el cache expiró (>24h), debe llamar a la API."""
        mock_engram = MagicMock()
        mock_engram.search.return_value = [{"id": "obs-1"}]
        mock_engram.get_observation.return_value = {
            "models": ["old-model"],
            "fetched_at": "2000-01-01T00:00:00",  # muy viejo
        }

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"data": [{"id": "new-model"}]}

        with patch("app.core.llm_validator.httpx.get", return_value=mock_response):
            models = get_available_models(
                "https://api.openai.com/v1",
                "sk-test",
                user_id=1,
                engram_client=mock_engram,
            )
            assert models == ["new-model"]  # vino de la API porque cache expiró
