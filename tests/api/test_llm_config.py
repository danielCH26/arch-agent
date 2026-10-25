"""
Tests para /api/llm/* — config y validate.
"""

import pytest
from unittest.mock import MagicMock, patch

from app.core.llm_validator import LLMValidationError, validate_llm_config


class TestLLMConfigModels:
    """Tests de Pydantic models."""

    def test_llm_config_out_model(self):
        from app.api.llm_config import LLMConfigOut

        out = LLMConfigOut(base_url="https://api.openai.com/v1", model="gpt-4o", has_api_key=True)
        assert out.base_url == "https://api.openai.com/v1"
        assert out.model == "gpt-4o"
        assert out.has_api_key is True

    def test_llm_config_out_without_key(self):
        from app.api.llm_config import LLMConfigOut

        out = LLMConfigOut(base_url=None, model=None, has_api_key=False)
        assert out.base_url is None
        assert out.has_api_key is False

    def test_llm_config_save_model(self):
        from app.api.llm_config import LLMConfigSave

        req = LLMConfigSave(
            base_url="https://api.openai.com/v1",
            model="gpt-4o",
            api_key="sk-test",
        )
        assert req.base_url == "https://api.openai.com/v1"
        assert req.api_key == "sk-test"

    def test_validate_request_model(self):
        from app.api.llm_config import ValidateRequest

        req = ValidateRequest(
            base_url="https://api.openai.com/v1",
            api_key="sk-test",
            model="gpt-4o",
        )
        assert req.base_url == "https://api.openai.com/v1"

    def test_validate_response_model(self):
        from app.api.llm_config import ValidateResponse

        resp = ValidateResponse(valid=True, message="Configuración válida")
        assert resp.valid is True
        assert resp.message == "Configuración válida"


class TestValidateLLMConfig:
    """Tests de validate_llm_config (función pura sin DB)."""

    @patch("app.core.llm_validator.httpx.get")
    def test_validate_success(self, mock_get):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_get.return_value = mock_response

        result = validate_llm_config("https://api.openai.com/v1", "sk-test")
        assert result is True
        mock_get.assert_called_once()
        call_args = mock_get.call_args
        assert "Authorization" in call_args.kwargs["headers"]

    @patch("app.core.llm_validator.httpx.get")
    def test_validate_401_unauthorized(self, mock_get):
        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_get.return_value = mock_response

        with pytest.raises(LLMValidationError) as exc_info:
            validate_llm_config("https://api.openai.com/v1", "bad-key")
        assert "API Key inválida" in str(exc_info.value)

    @patch("app.core.llm_validator.httpx.get")
    def test_validate_404_not_found(self, mock_get):
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_get.return_value = mock_response

        with pytest.raises(LLMValidationError) as exc_info:
            validate_llm_config("https://bad-url.com/v1", "sk-test")
        # Error message: "La URL no existe o no es un endpoint /models válido."
        assert "URL" in str(exc_info.value) or "404" in str(exc_info.value)

    @patch("app.core.llm_validator.httpx.get")
    def test_validate_timeout(self, mock_get):
        import httpx

        mock_get.side_effect = httpx.TimeoutException("timeout")

        with pytest.raises(LLMValidationError) as exc_info:
            validate_llm_config("https://api.openai.com/v1", "sk-test")
        # Error message: "El proveedor no respondió en {DEFAULT_TIMEOUT}s. Verifica tu conexión."
        assert "proveedor" in str(exc_info.value) or "respondi" in str(exc_info.value)

    @patch("app.core.llm_validator.httpx.get")
    def test_validate_connect_error(self, mock_get):
        import httpx

        mock_get.side_effect = httpx.ConnectError("connection refused")

        with pytest.raises(LLMValidationError) as exc_info:
            validate_llm_config("https://localhost:9999/v1", "sk-test")
        # Error message: "No se pudo conectar al proveedor: ..."
        assert "conectar" in str(exc_info.value) or "conexi" in str(exc_info.value)

    def test_validate_missing_credentials(self):
        with pytest.raises(LLMValidationError) as exc_info:
            validate_llm_config("", "sk-test")
        assert "obligatorios" in str(exc_info.value)


class TestLLMConfigAPI:
    """Tests de los endpoints REST de LLM config."""

    def test_llm_config_out_never_exposes_api_key(self):
        """Verify LLMConfigOut model has no api_key field."""
        from app.api.llm_config import LLMConfigOut

        out = LLMConfigOut(
            base_url="https://api.openai.com/v1",
            model="gpt-4o",
            has_api_key=True,
        )
        assert out.has_api_key is True
        assert not hasattr(out, "api_key")
        assert not hasattr(out, "encrypted_api_key")

    def test_llm_config_out_fields_are_public(self):
        """Verify all fields returned to the client are public info."""
        from app.api.llm_config import LLMConfigOut

        out = LLMConfigOut(base_url="https://api.openai.com/v1", model="gpt-4o", has_api_key=True)
        # These are the only fields
        assert hasattr(out, "base_url")
        assert hasattr(out, "model")
        assert hasattr(out, "has_api_key")
