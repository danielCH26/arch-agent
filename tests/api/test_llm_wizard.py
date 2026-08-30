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
        """URL con 404 falla con 400 'no es compatible con OpenAI'."""
        mock_get.return_value = _mock_response(404)

        import asyncio
        from app.api.llm_config import wizard_step1

        body = WizardStep1Request(base_url="https://bad-url.example/v1")

        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(wizard_step1(body, _current_user()))

        assert exc_info.value.status_code == 400
        assert "no es compatible con openai" in exc_info.value.detail.lower()

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

    def test_empty_url_fails(self):
        """URL vacía falla con 400 'URL es obligatoria'."""
        import asyncio
        from app.api.llm_config import wizard_step1

        body = WizardStep1Request(base_url="")

        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(wizard_step1(body, _current_user()))

        assert exc_info.value.status_code == 400
        assert "obligatoria" in exc_info.value.detail.lower()

    def test_whitespace_only_url_fails(self):
        """URL con solo espacios falla con 400 'URL es obligatoria'."""
        import asyncio
        from app.api.llm_config import wizard_step1

        body = WizardStep1Request(base_url="   ")

        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(wizard_step1(body, _current_user()))

        assert exc_info.value.status_code == 400
        assert "obligatoria" in exc_info.value.detail.lower()

    def test_url_without_protocol_fails(self):
        """URL sin protocolo falla con 400 'debe comenzar con http'."""
        import asyncio
        from app.api.llm_config import wizard_step1

        body = WizardStep1Request(base_url="api.openai.com/v1")

        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(wizard_step1(body, _current_user()))

        assert exc_info.value.status_code == 400
        assert "http:// o https://" in exc_info.value.detail.lower()

    def test_url_with_only_scheme_fails(self):
        """URL con solo esquema (https://) falla con 400 'Ingresá el host'."""
        import asyncio
        from app.api.llm_config import wizard_step1

        body = WizardStep1Request(base_url="https://")

        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(wizard_step1(body, _current_user()))

        assert exc_info.value.status_code == 400
        assert "host" in exc_info.value.detail.lower()

    def test_url_with_scheme_and_path_but_no_host_fails(self):
        """URL con esquema y path pero sin host falla con 400 'Ingresá el host'."""
        import asyncio
        from app.api.llm_config import wizard_step1

        body = WizardStep1Request(base_url="https:///v1")

        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(wizard_step1(body, _current_user()))

        assert exc_info.value.status_code == 400
        assert "host" in exc_info.value.detail.lower()

    def test_valid_url_passes(self):
        """URL válida pasa la validación de formato."""
        import asyncio
        from app.api.llm_config import _validate_url_format

        # No debe lanzar excepción
        _validate_url_format("https://api.openai.com/v1")

    def test_valid_localhost_url_passes(self):
        """URL localhost pasa la validación."""
        import asyncio
        from app.api.llm_config import _validate_url_format

        # No debe lanzar excepción
        _validate_url_format("http://localhost:11434/v1")

    def test_valid_ip_url_passes(self):
        """URL con IP literal pasa la validación."""
        import asyncio
        from app.api.llm_config import _validate_url_format

        # No debe lanzar excepción
        _validate_url_format("https://192.168.0.10:8080/v1")

    @patch("app.api.llm_config.httpx.get")
    def test_connect_error_fails(self, mock_get):
        """ConnectError falla con mensaje específico."""
        import httpx
        mock_get.side_effect = httpx.ConnectError("connection failed")

        import asyncio
        from app.api.llm_config import wizard_step1

        body = WizardStep1Request(base_url="https://unreachable.example/v1")

        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(wizard_step1(body, _current_user()))

        assert exc_info.value.status_code == 400
        assert "no se pudo conectar" in exc_info.value.detail.lower()


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

    def test_empty_api_key_fails_when_no_prior_config(self):
        """API key vacia falla si el usuario no tiene config previa guardada."""
        from app.core.llm_loader import LLMConfigError
        from app.api import llm_config as llm_config_module

        import asyncio
        from app.api.llm_config import wizard_step3

        # Mock: load_user_llm_config no encuentra config previa
        with patch.object(llm_config_module, "load_user_llm_config") as mock_load:
            mock_load.side_effect = LLMConfigError("no hay config")

            body = WizardStep3Request(
                base_url="https://api.openai.com/v1",
                api_key="",
                model="gpt-4o",
                allow_unknown_model=False,
            )

            with pytest.raises(HTTPException) as exc_info:
                asyncio.run(wizard_step3(body, _current_user()))

        assert exc_info.value.status_code == 400
        assert "api key" in exc_info.value.detail.lower()

    @patch("app.api.llm_config.save_user_llm_config")
    def test_empty_api_key_reuses_saved_config(self, mock_save):
        """API key vacia pero con config previa: el endpoint reuse la guardada."""
        from app.api import llm_config as llm_config_module

        import asyncio
        from app.api.llm_config import wizard_step3

        # Mock: load_user_llm_config devuelve config con api_key
        mock_existing = MagicMock()
        mock_existing.api_key = "sk-saved-test-key"

        with patch.object(llm_config_module, "load_user_llm_config") as mock_load:
            mock_load.return_value = mock_existing

            body = WizardStep3Request(
                base_url="https://api.openai.com/v1",
                api_key=None,  # no enviada
                model="gpt-4o",
                allow_unknown_model=False,
            )

            result = asyncio.run(wizard_step3(body, _current_user()))

        assert result.success is True
        # Verifica que save_user_llm_config recibio la api_key guardada, no vacia
        save_kwargs = mock_save.call_args.kwargs
        assert save_kwargs["api_key"] == "sk-saved-test-key"
        assert save_kwargs["model"] == "gpt-4o"


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

# --- Available models endpoint ----------------------------------------------

class TestAvailableModelsEndpoint:
    """GET /api/llm/wizard/available-models"""

    @patch("app.api.llm_config.get_available_models")
    @patch("app.core.llm_loader.SessionLocal")
    def test_returns_models_from_provider(self, mock_session, mock_get_models):
        """Endpoint exitoso: devuelve lista + base_url."""
        # Generar API key encriptada valida con la ENCRYPTION_KEY del conftest
        from cryptography.fernet import Fernet
        from app.core.encryption import encrypt

        encrypted_key = encrypt("sk-test-plain-key")

        # Mock user con config
        mock_user = MagicMock()
        mock_user.id = 1
        mock_user.llm_base_url = "https://api.openai.com/v1"
        mock_user.llm_model = "gpt-4o"
        mock_user.encrypted_api_key = encrypted_key

        mock_db = MagicMock()
        mock_db.get.return_value = mock_user
        mock_session.return_value = mock_db

        # Mock get_available_models para devolver lista
        mock_get_models.return_value = ["gpt-4o", "gpt-4o-mini", "o1"]

        import asyncio
        from app.api.llm_config import wizard_available_models

        result = asyncio.run(wizard_available_models(_current_user()))

        assert result.models == ["gpt-4o", "gpt-4o-mini", "o1"]
        assert result.base_url == "https://api.openai.com/v1"
        # NO debe devolver api_key
        assert not hasattr(result, "api_key")

    @patch("app.core.llm_loader.SessionLocal")
    def test_returns_404_when_no_config(self, mock_session):
        """Sin config guardada, endpoint retorna 404."""
        # Mock para que load_user_llm_config falle (no hay config)
        mock_user = MagicMock()
        mock_user.id = 1
        mock_user.llm_base_url = None  # no hay config
        mock_user.llm_model = None
        mock_user.encrypted_api_key = None

        mock_db = MagicMock()
        mock_db.get.return_value = mock_user
        mock_session.return_value = mock_db

        import asyncio
        from app.api.llm_config import wizard_available_models

        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(wizard_available_models(_current_user()))

        assert exc_info.value.status_code == 404

    @patch("app.api.llm_config.get_available_models")
    @patch("app.core.llm_loader.SessionLocal")
    def test_provider_error_returns_400(self, mock_session, mock_get_models):
        """Si el provider falla, endpoint retorna 400."""
        from cryptography.fernet import Fernet
        from app.core.encryption import encrypt
        from app.core.llm_validator import LLMValidationError

        encrypted_key = encrypt("sk-test-plain-key")

        mock_user = MagicMock()
        mock_user.id = 1
        mock_user.llm_base_url = "https://api.openai.com/v1"
        mock_user.llm_model = "gpt-4o"
        mock_user.encrypted_api_key = encrypted_key

        mock_db = MagicMock()
        mock_db.get.return_value = mock_user
        mock_session.return_value = mock_db

        mock_get_models.side_effect = LLMValidationError("404 not found", status_code=404)

        import asyncio
        from app.api.llm_config import wizard_available_models

        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(wizard_available_models(_current_user()))

        assert exc_info.value.status_code == 400
        assert "No se pudo listar" in exc_info.value.detail
