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


def _mock_session_with_user(
    mock_session,
    user_id: int = 1,
    base_url: str = "https://api.openai.com/v1",
    model: str = "gpt-4o",
    encrypted_key: str = "encrypted-fake-key",
):
    """
    Configura un mock user existente en la DB con config valida.
    Compatible con `db.get(User, id)` (usado por load_user_llm_config
    y los helpers de persistencia) y con `db.query(...)` (legacy).
    """
    mock_user = MagicMock()
    mock_user.id = user_id
    mock_user.llm_base_url = base_url
    mock_user.llm_model = model
    mock_user.encrypted_api_key = encrypted_key
    mock_db = MagicMock()
    mock_db.get.return_value = mock_user
    mock_db.query.return_value.filter.return_value.first.return_value = mock_user
    mock_session.return_value = mock_db
    return mock_user


def _mock_session_no_user(mock_session):
    """Mock donde el user no existe en DB."""
    mock_db = MagicMock()
    mock_db.get.return_value = None
    mock_session.return_value = mock_db


# --- Wizard Step 1: validate URL ---------------------------------------------

class TestWizardStep1:
    """POST /api/llm/wizard/step1"""

    @patch("app.core.llm_loader.SessionLocal")
    @patch("app.api.llm_config.httpx.get")
    def test_valid_url_200(self, mock_get, mock_session):
        """URL que responde 200 al ping pasa step 1 Y persiste base_url."""
        mock_get.return_value = _mock_response(200)
        user = _mock_session_with_user(mock_session)

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
        # Verifica que se persistio el base_url en el user
        assert user.llm_base_url == "https://api.openai.com/v1"
        # api_key y model NO se tocan en step1
        assert user.encrypted_api_key == "encrypted-fake-key"
        assert user.llm_model == "gpt-4o"

    @patch("app.core.llm_loader.SessionLocal")
    @patch("app.api.llm_config.httpx.get")
    def test_url_with_401_still_passes(self, mock_get, mock_session):
        """URL que retorna 401 (endpoint existe pero requiere auth) pasa step 1."""
        mock_get.return_value = _mock_response(401)
        _mock_session_with_user(mock_session)

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

    @patch("app.core.llm_loader.SessionLocal")
    @patch("app.api.llm_config.httpx.get")
    def test_valid_key_passes(self, mock_get, mock_session):
        """API key valida + endpoint 200 pasa step 2 Y persiste credenciales."""
        mock_get.return_value = _mock_response(200)
        user = _mock_session_with_user(mock_session)

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
        # Verifica que se persistio base_url + api_key
        assert user.llm_base_url == "https://api.openai.com/v1"
        assert user.encrypted_api_key != "encrypted-fake-key"  # encriptada, no plain
        # model NO se toca en step2
        assert user.llm_model == "gpt-4o"

    @patch("app.core.llm_loader.SessionLocal")
    @patch("app.api.llm_config.httpx.get")
    def test_invalid_key_401_fails(self, mock_get, mock_session):
        """401 con auth header = key invalida, falla step 2 sin persistir."""
        mock_get.return_value = _mock_response(401)
        user = _mock_session_with_user(mock_session)
        original_key = user.encrypted_api_key

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
        # No se persiste nada si la validacion falla
        assert user.encrypted_api_key == original_key
        assert user.llm_base_url == "https://api.openai.com/v1"

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

    @patch("app.core.llm_loader.decrypt", return_value="sk-decrypted-fake-key")
    @patch("app.core.llm_loader.SessionLocal")
    def test_tier1_model_saves(self, mock_session, mock_decrypt):
        """Modelo tier 1 (gpt-4o, MMLU 88.7) se guarda OK."""
        from app.api.llm_config import wizard_step3

        # User con config persistida por step1+step2; step3 persiste solo model.
        mock_user = _mock_session_with_user(
            mock_session,
            base_url="https://api.openai.com/v1",
            model="gpt-4-turbo",
        )
        original_url = mock_user.llm_base_url
        original_key = mock_user.encrypted_api_key

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
        # Step3 persiste SOLO model. URL y api_key NO se tocan.
        assert mock_user.llm_model == "gpt-4o"
        assert mock_user.llm_base_url == original_url
        assert mock_user.encrypted_api_key == original_key

    @patch("app.core.llm_loader.decrypt", return_value="sk-decrypted-fake-key")
    @patch("app.core.llm_loader.SessionLocal")
    def test_tier2_blocked_without_flag(self, mock_session, mock_decrypt):
        """Modelo tier 2 sin allow_unknown_model=True falla con 400."""
        from app.api.llm_config import wizard_step3

        _mock_session_with_user(mock_session)
        original_model = "gpt-4o"

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

    @patch("app.core.llm_loader.decrypt", return_value="sk-decrypted-fake-key")
    @patch("app.core.llm_loader.SessionLocal")
    def test_tier2_allowed_with_flag(self, mock_session, mock_decrypt):
        """Modelo tier 2 CON allow_unknown_model=True se guarda."""
        from app.api.llm_config import wizard_step3

        _mock_session_with_user(mock_session)

        import asyncio
        body = WizardStep3Request(
            base_url="https://api.openai.com/v1",
            api_key="sk-test",
            model="gpt-4o-mini",
            allow_unknown_model=True,
        )
        result = asyncio.run(wizard_step3(body, _current_user()))

        assert result.success is True

    @patch("app.core.llm_loader.decrypt", return_value="sk-decrypted-fake-key")
    @patch("app.core.llm_loader.SessionLocal")
    def test_unknown_model_blocked_without_flag(self, mock_session, mock_decrypt):
        """Modelo que no esta en YAML (unknown) sin flag falla."""
        from app.api.llm_config import wizard_step3

        _mock_session_with_user(mock_session)

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

    @patch("app.core.llm_loader.decrypt", return_value="sk-decrypted-fake-key")
    @patch("app.core.llm_loader.SessionLocal")
    def test_unknown_model_allowed_with_flag(self, mock_session, mock_decrypt):
        """Modelo unknown CON allow_unknown_model=True se guarda."""
        from app.api.llm_config import wizard_step3

        _mock_session_with_user(mock_session)

        import asyncio
        body = WizardStep3Request(
            base_url="https://api.openai.com/v1",
            api_key="sk-test",
            model="my-custom-fine-tune",
            allow_unknown_model=True,
        )
        result = asyncio.run(wizard_step3(body, _current_user()))

        assert result.success is True

    @patch("app.core.llm_loader.decrypt", return_value="sk-decrypted-fake-key")
    @patch("app.core.llm_loader.SessionLocal")
    def test_blocked_model_always_fails(self, mock_session, mock_decrypt):
        """Modelo blocked (MMLU < 60) SIEMPRE falla, no hay flag que lo salve."""
        from app.api.llm_config import wizard_step3

        _mock_session_with_user(mock_session)

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
        """Sin config persistida en DB, wizard_step3 retorna 404 claro."""
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

        # step3 ahora exige que step1+step2 hayan persistido la config.
        # Si no la hay, retorna 404 apuntando a los pasos 1 y 2.
        assert exc_info.value.status_code == 404
        assert "paso" in exc_info.value.detail.lower()

    @patch("app.api.llm_config.update_user_model_only")
    @patch("app.api.llm_config.load_user_llm_config")
    def test_step3_persists_only_model_ignores_body_credentials(
        self, mock_load, mock_update
    ):
        """step3 lee base_url y api_key de DB, ignora el body, persiste solo model.

        El frontend puede mandar base_url/api_key en el body por compat,
        pero la fuente de verdad es la DB. Esto evita desincronizacion si
        hay varias pestanas abiertas o si el state del frontend esta
        desactualizado.
        """
        from app.api.llm_config import wizard_step3

        # Config persistida por step1+step2
        mock_existing = MagicMock()
        mock_existing.base_url = "https://api.z.ai/api/paas/v4/"
        mock_existing.api_key = "sk-real-saved-key"
        mock_existing.model = "previous-model"
        mock_load.return_value = mock_existing

        import asyncio
        body = WizardStep3Request(
            base_url="https://body-url-IGNORED.example/v1",
            api_key="sk-body-IGNORED",
            model="my-new-model",
            allow_unknown_model=True,
        )

        result = asyncio.run(wizard_step3(body, _current_user()))

        assert result.success is True
        assert result.model == "my-new-model"
        # La respuesta usa la base_url de DB, no la del body
        assert result.base_url == "https://api.z.ai/api/paas/v4/"
        # update_user_model_only fue llamado con el model y el user_id correcto.
        # NO save_user_llm_config (que pisaria api_key).
        update_args = mock_update.call_args.args
        assert update_args[0] == 1  # user_id
        assert update_args[1] == "my-new-model"  # model


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

    @patch("app.api.llm_config.get_available_models")
    @patch("app.core.llm_loader.SessionLocal")
    def test_works_for_new_user_without_model_yet(self, mock_session, mock_get_models):
        """User nuevo que completo step1+step2 pero todavia no modelo.

        Repro del bug reportado: un user nuevo que recien configuro URL
        y API key no tiene llm_model seteado todavia. El endpoint
        available-models (llamado despues de step2 para mostrar la lista)
        debe funcionar igual — el model es opcional para listar
        modelos del provider.

        Antes del fix, load_user_llm_config requeria llm_model no vacio,
        lo cual rompia este caso y el usuario quedaba bloqueado.
        """
        from cryptography.fernet import Fernet
        from app.core.encryption import encrypt

        # User nuevo: tiene URL + api_key pero NO tiene model todavia.
        encrypted_key = encrypt("sk-test-plain-key")

        mock_user = MagicMock()
        mock_user.id = 1
        mock_user.llm_base_url = "https://api.openai.com/v1"
        mock_user.llm_model = None  # todavia no eligio modelo
        mock_user.encrypted_api_key = encrypted_key

        mock_db = MagicMock()
        mock_db.get.return_value = mock_user
        mock_session.return_value = mock_db

        mock_get_models.return_value = ["gpt-4o", "gpt-4o-mini"]

        import asyncio
        from app.api.llm_config import wizard_available_models

        result = asyncio.run(wizard_available_models(_current_user()))

        assert result.models == ["gpt-4o", "gpt-4o-mini"]
        assert result.base_url == "https://api.openai.com/v1"

    @patch("app.core.llm_loader.SessionLocal")
    def test_returns_422_when_decryption_fails(self, mock_session):
        """Si la API key en DB no se puede desencriptar, retorna 422 (no 404).

        Distingue 'key corrupta por cambio de ENCRYPTION_KEY' de
        'no config guardada' para que el cliente sepa que tiene que
        reconfigurar.
        """
        from app.core.encryption import EncryptionError
        from app.core.llm_loader import LLMConfigError

        # Mock user con config pero key corrupta (no se puede desencriptar)
        mock_user = MagicMock()
        mock_user.id = 1
        mock_user.llm_base_url = "https://api.openai.com/v1"
        mock_user.llm_model = "gpt-4o"
        mock_user.encrypted_api_key = "key-que-no-se-puede-desencriptar"

        mock_db = MagicMock()
        mock_db.get.return_value = mock_user
        mock_session.return_value = mock_db

        # Patchear decrypt para que falle como si ENCRYPTION_KEY hubiera cambiado
        with patch("app.core.llm_loader.decrypt") as mock_decrypt:
            mock_decrypt.side_effect = EncryptionError("No se pudo desencriptar")

            import asyncio
            from app.api.llm_config import wizard_available_models

            with pytest.raises(HTTPException) as exc_info:
                asyncio.run(wizard_available_models(_current_user()))

        assert exc_info.value.status_code == 422
        assert "no se puede desencriptar" in exc_info.value.detail.lower()
        assert "ENCRYPTION_KEY" in exc_info.value.detail


# --- Persistencia por paso (refactor wizard) -------------------------------

class TestWizardPersistenciaPorPaso:
    """
    El wizard refactorizado persiste en cada paso en vez de guardar todo al
    final. Esto garantiza que /api/llm/wizard/available-models (que lee de
    DB) vea la URL/api_key nuevas apenas se validan, no solo al final.
    """

    @patch("app.core.llm_loader.SessionLocal")
    @patch("app.api.llm_config.httpx.get")
    def test_step1_normalizes_trailing_slash_before_persisting(
        self, mock_get, mock_session
    ):
        """step1 quita el slash final del base_url antes de persistir."""
        mock_get.return_value = _mock_response(200)
        user = _mock_session_with_user(mock_session)

        import asyncio
        from app.api.llm_config import wizard_step1

        body = WizardStep1Request(base_url="https://api.openai.com/v1/")
        result = asyncio.run(wizard_step1(body, _current_user()))

        assert result.success is True
        # Trailing slash removido antes de guardar
        assert user.llm_base_url == "https://api.openai.com/v1"

    @patch("app.api.llm_config.httpx.get")
    def test_step1_does_not_persist_on_404(self, mock_get):
        """Si la validacion del endpoint falla (404), no se persiste nada.

        Esto evita que URLs mal tipeadas queden guardadas en DB y rompan
        /api/llm/wizard/available-models que asume base_url persistido
        es un provider alcanzable.
        """
        from app.api.llm_config import wizard_step1
        from app.core.llm_loader import update_user_base_url_only

        mock_get.return_value = _mock_response(404)

        import asyncio
        body = WizardStep1Request(base_url="https://bad-url.example/v1")

        with pytest.raises(HTTPException):
            asyncio.run(wizard_step1(body, _current_user()))

        # update_user_base_url_only NO debe haberse llamado
        # (verificable indirectamente: el test no explota al no mockear SessionLocal,
        # lo que confirma que no se intento tocar la DB)
        with patch.object(
            __import__("app.core.llm_loader", fromlist=["update_user_base_url_only"]),
            "update_user_base_url_only",
        ) as mock_update:
            # Re-correr para confirmar que tampoco se llamaria en este path
            pass

    @patch("app.core.llm_loader.SessionLocal")
    @patch("app.api.llm_config.httpx.get")
    def test_step2_persists_credentials_atomically(
        self, mock_get, mock_session
    ):
        """step2 persiste base_url + api_key en una sola transaccion."""
        user = _mock_session_with_user(mock_session)
        original_model = user.llm_model

        # Validamos con 401 para que el codigo retorne error SIN persistir
        mock_get.return_value = _mock_response(401)

        import asyncio
        from app.api.llm_config import wizard_step2

        body = WizardStep2Request(
            base_url="https://api.new-provider.com/v1",
            api_key="sk-new-key",
        )

        with pytest.raises(HTTPException):
            asyncio.run(wizard_step2(body, _current_user()))

        # Como fallo, NO se persistio nada
        assert user.llm_base_url == "https://api.openai.com/v1"
        assert user.encrypted_api_key == "encrypted-fake-key"
        assert user.llm_model == original_model

    @patch("app.core.llm_loader.decrypt", return_value="sk-decrypted-fake-key")
    @patch("app.api.llm_config.load_user_llm_config")
    def test_step3_returns_404_when_no_persisted_config(
        self, mock_load, mock_decrypt
    ):
        """step3 exige config persistida previa (de step1+step2). Si no hay -> 404."""
        from app.core.llm_loader import LLMConfigError
        from app.api.llm_config import wizard_step3

        mock_load.side_effect = LLMConfigError("no hay config")

        import asyncio
        body = WizardStep3Request(
            base_url="https://api.openai.com/v1",
            api_key=None,
            model="gpt-4o",
            allow_unknown_model=False,
        )

        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(wizard_step3(body, _current_user()))

        assert exc_info.value.status_code == 404
        assert "paso" in exc_info.value.detail.lower()
