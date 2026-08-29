"""
Tests para los endpoints del wizard LLM (issue #51).

Mockeamos httpx para no pegar a providers reales. Cubrimos:
- step1 URL valida / invalida
- step2 key valida / invalida / faltante
- step3 tier1 OK, tier2 bloqueado sin flag, tier2 OK con flag,
  blocked siempre 400, unknown OK con flag, modelo faltante 400
- /config/validate viejo retorna 410
"""

import pytest
from unittest.mock import MagicMock, patch
from fastapi import HTTPException

from app.api.llm_config import (
    WizardStep1Request,
    WizardStep2Request,
    WizardStep3Request,
    ValidateRequest,
)
from app.api.dependencies import JWT_REVOKED
from app.core.jwt import create_access_token, verify_token


# --- Helpers -----------------------------------------------------------------

def _mock_response(status_code: int, text: str = ""):
    r = MagicMock()
    r.status_code = status_code
    r.text = text
    return r


def _current_user(user_id: int = 1, username: str = "testuser"):
    return {"user_id": user_id, "username": username, "jti": None}


# --- Wizard Step 1: validate URL ---------------------------------------------

class TestWizardStep1:
    """POST /api/llm/wizard/step1"""

    @patch("app.api.llm_config.httpx.get")
    def test_valid_url_200(self, mock_get):
        """URL que responde 200 al ping pasa step 1."""
        mock_get.return_value = _mock_response(200)

        # Importamos la función asyncrona y la ejecutamos con asyncio
        import asyncio
        from app.api.llm_config import wizard_step1

        body = WizardStep1Request(base_url="https://api.openai.com/v1")
        result = asyncio.run(wizard_step1(body, _current_user()))

        assert result.success is True
        assert "URL válida" in result.message
        mock_get.assert_called_once()
        # Verifica que se llamó sin Authorization (sin key en step 1)
        call_kwargs = mock_get.call_args.kwargs
        assert "Authorization" not in call_kwargs.get("headers", {})

    @patch("app.api.llm_config.httpx.get")
    def test_url_with_401_still_passes(self, mock_get):
        """URL que retorna 401 (endpoint existe pero requiere auth) pasa step 1."""
        mock_get.return_value = _mock_response(401)

        import asyncio
        from app.api.llm_config import wizard_step1

        body = WizardStep1Request(base_url="https://api.example.com/v1")
        result = asyncio.run(wizard_step1(body, _current_user()))

        assert result.success is True

    @patch("app.api.llm_config.httpx.get")
    def test_url_with_404_fails(self, mock_get):
        """URL con 404 falla con 400 'URL no existe'."""
        mock_get.return_value = _mock_response(404)

        import asyncio
        from app.api.llm_config import wizard_step1

        body = WizardStep1Request(base_url="https://bad-url.example/v1")

        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(wizard_step1(body, _current_user()))

        assert exc_info.value.status_code == 400
        assert "no existe" in exc_info.value.detail.lower()

    @patch("app.api.llm_config.httpx.get")
    def test_url_timeout_fails(self, mock_get):
        """Timeout del provider falla con mensaje específico."""
        import httpx
        mock_get.side_effect = httpx.TimeoutException("timeout")

        import asyncio
        from app.api.llm_config import wizard_step1

        body = WizardStep1Request(base_url="https://slow.example/v1")

        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(wizard_step1(body, _current_user()))

        assert exc_info.value.status_code == 400
        assert "10" in exc_info.value.detail  # menciona el timeout

    def test_invalid_url_format_fails(self):
        """URL sin http:// falla sin pegar al provider."""
        import asyncio
        from app.api.llm_config import wizard_step1

        body = WizardStep1Request(base_url="not-a-url")

        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(wizard_step1(body, _current_user()))

        assert exc_info.value.status_code == 400
        assert "http" in exc_info.value.detail.lower()


# --- Wizard Step 2: validate API key + connection ---------------------------

class TestWizardStep2:
    """POST /api/llm/wizard/step2"""

    @patch("app.api.llm_config.httpx.get")
    def test_valid_key_passes(self, mock_get):
        """API key válida + endpoint 200 pasa step 2."""
        mock_get.return_value = _mock_response(200)

        import asyncio
        from app.api.llm_config import wizard_step2

        body = WizardStep2Request(
            base_url="https://api.openai.com/v1",
            api_key="sk-valid-test-key",
        )
        result = asyncio.run(wizard_step2(body, _current_user()))

        assert result.success is True
        # Verifica que se llamó CON Authorization Bearer
        call_kwargs = mock_get.call_args.kwargs
        assert call_kwargs["headers"]["Authorization"] == "Bearer sk-valid-test-key"

    @patch("app.api.llm_config.httpx.get")
    def test_invalid_key_401_fails(self, mock_get):
        """401 con auth header = key inválida, falla step 2."""
        mock_get.return_value = _mock_response(401)

        import asyncio
        from app.api.llm_config import wizard_step2

        body = WizardStep2Request(
            base_url="https://api.openai.com/v1",
            api_key="bad-key",
        )

        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(wizard_step2(body, _current_user()))

        assert exc_info.value.status_code == 400
        assert "API Key inválida" in exc_info.value.detail

    def test_empty_key_fails(self):
        """API key vacía falla sin pegar al provider."""
        import asyncio
        from app.api.llm_config import wizard_step2

        body = WizardStep2Request(
            base_url="https://api.openai.com/v1",
            api_key="",
        )

        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(wizard_step2(body, _current_user()))

        assert exc_info.value.status_code == 400


# --- Wizard Step 3: save config with tier enforcement ----------------------

class TestWizardStep3:
    """POST /api/llm/wizard/step3"""

    @patch("app.core.llm_loader.SessionLocal")
    def test_tier1_model_saves(self, mock_session):
        """Modelo tier 1 (gpt-4o, MMLU 88.7) se guarda OK."""
        from datetime import datetime
        from app.api.llm_config import wizard_step3

        # Mock user con config previa
        mock_user = MagicMock()
        mock_user.id = 1
        mock_user.llm_base_url = None
        mock_user.llm_model = None
        mock_user.encrypted_api_key = None

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = mock_user
        mock_session.return_value = mock_db

        import asyncio
        body = WizardStep3Request(
            base_url="https://api.openai.com/v1",
            api_key="sk-test",
            model="gpt-4o",
            allow_unknown_model=False,
        )
        result = asyncio.run(wizard_step3(body, _current_user()))

        assert result.success is True
        assert result.model == "gpt-4o"

    @patch("app.core.llm_loader.SessionLocal")
    def test_tier2_blocked_without_flag(self, mock_session):
        """Modelo tier 2 sin allow_unknown_model=True falla con 400."""
        from app.api.llm_config import wizard_step3

        mock_user = MagicMock()
        mock_user.id = 1
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = mock_user
        mock_session.return_value = mock_db

        import asyncio
        body = WizardStep3Request(
            base_url="https://api.openai.com/v1",
            api_key="sk-test",
            model="gpt-4o-mini",  # tier 2
            allow_unknown_model=False,
        )

        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(wizard_step3(body, _current_user()))

        assert exc_info.value.status_code == 400
        assert "tier 1" in exc_info.value.detail.lower()

    @patch("app.core.llm_loader.SessionLocal")
    def test_tier2_allowed_with_flag(self, mock_session):
        """Modelo tier 2 CON allow_unknown_model=True se guarda."""
        from app.api.llm_config import wizard_step3

        mock_user = MagicMock()
        mock_user.id = 1
        mock_user.llm_base_url = None
        mock_user.llm_model = None
        mock_user.encrypted_api_key = None

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = mock_user
        mock_session.return_value = mock_db

        import asyncio
        body = WizardStep3Request(
            base_url="https://api.openai.com/v1",
            api_key="sk-test",
            model="gpt-4o-mini",
            allow_unknown_model=True,
        )
        result = asyncio.run(wizard_step3(body, _current_user()))

        assert result.success is True

    @patch("app.core.llm_loader.SessionLocal")
    def test_unknown_model_blocked_without_flag(self, mock_session):
        """Modelo que no esta en YAML (unknown) sin flag falla."""
        from app.api.llm_config import wizard_step3

        mock_user = MagicMock()
        mock_user.id = 1
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = mock_user
        mock_session.return_value = mock_db

        import asyncio
        body = WizardStep3Request(
            base_url="https://api.openai.com/v1",
            api_key="sk-test",
            model="some-future-model-2027",
            allow_unknown_model=False,
        )

        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(wizard_step3(body, _current_user()))

        assert exc_info.value.status_code == 400

    @patch("app.core.llm_loader.SessionLocal")
    def test_unknown_model_allowed_with_flag(self, mock_session):
        """Modelo unknown CON allow_unknown_model=True se guarda."""
        from app.api.llm_config import wizard_step3

        mock_user = MagicMock()
        mock_user.id = 1
        mock_user.llm_base_url = None
        mock_user.llm_model = None
        mock_user.encrypted_api_key = None

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = mock_user
        mock_session.return_value = mock_db

        import asyncio
        body = WizardStep3Request(
            base_url="https://api.openai.com/v1",
            api_key="sk-test",
            model="my-custom-fine-tune",
            allow_unknown_model=True,
        )
        result = asyncio.run(wizard_step3(body, _current_user()))

        assert result.success is True

    @patch("app.core.llm_loader.SessionLocal")
    def test_blocked_model_always_fails(self, mock_session):
        """Modelo blocked (MMLU < 60) SIEMPRE falla, no hay flag que lo salve."""
        from app.api.llm_config import wizard_step3

        mock_user = MagicMock()
        mock_user.id = 1
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = mock_user
        mock_session.return_value = mock_db

        import asyncio
        body = WizardStep3Request(
            base_url="https://api.openai.com/v1",
            api_key="sk-test",
            model="gpt-3.5-turbo",  # blocked
            allow_unknown_model=True,  # intento override
        )

        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(wizard_step3(body, _current_user()))

        assert exc_info.value.status_code == 400
        assert "bloqueado" in exc_info.value.detail.lower()

    def test_empty_model_fails(self):
        """Modelo vacío falla sin pegar a la DB."""
        import asyncio
        from app.api.llm_config import wizard_step3

        body = WizardStep3Request(
            base_url="https://api.openai.com/v1",
            api_key="sk-test",
            model="",
            allow_unknown_model=False,
        )

        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(wizard_step3(body, _current_user()))

        assert exc_info.value.status_code == 400

    def test_empty_api_key_fails(self):
        """API key vacía falla."""
        import asyncio
        from app.api.llm_config import wizard_step3

        body = WizardStep3Request(
            base_url="https://api.openai.com/v1",
            api_key="",
            model="gpt-4o",
            allow_unknown_model=False,
        )

        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(wizard_step3(body, _current_user()))

        assert exc_info.value.status_code == 400


# --- Old /config/validate endpoint (deprecated) -----------------------------

class TestValidateDeprecated:
    """POST /api/llm/config/validate debe retornar 410 Gone."""

    def test_returns_410(self):
        import asyncio
        from app.api.llm_config import validate_config_deprecated

        body = ValidateRequest(
            base_url="https://api.openai.com/v1",
            api_key="sk-test",
            model="gpt-4o",
        )

        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(validate_config_deprecated(body))

        assert exc_info.value.status_code == 410
        assert "wizard" in exc_info.value.detail.lower()