"""
Tests para el loader de configuración LLM.

Issue: #7 - HU12 Configuración de LLM
"""

import pytest
from unittest.mock import MagicMock, patch

from app.core.llm_loader import (
    load_user_llm_config,
    save_user_llm_config,
    build_langchain_model,
    clear_session_cache,
    LLMConfigError,
)


@pytest.fixture(autouse=True)
def clear_cache():
    """Limpia el cache antes y después de cada test."""
    clear_session_cache()
    yield
    clear_session_cache()


class FakeUser:
    """Mock de User para tests."""
    def __init__(self, user_id, base_url=None, model=None, encrypted_api_key=None):
        self.id = user_id
        self.llm_base_url = base_url
        self.llm_model = model
        self.encrypted_api_key = encrypted_api_key


class TestLoadUserLLMConfig:
    """Tests de load_user_llm_config."""

    @patch("app.core.llm_loader.SessionLocal")
    def test_loads_config_successfully(self, mock_session_local):
        from app.core.encryption import encrypt

        user = FakeUser(
            user_id=1,
            base_url="https://api.openai.com/v1",
            model="gpt-4o-mini",
            encrypted_api_key=encrypt("sk-test"),
        )
        mock_db = MagicMock()
        mock_db.get.return_value = user
        mock_session_local.return_value = mock_db

        config = load_user_llm_config(1)
        assert config.user_id == 1
        assert config.base_url == "https://api.openai.com/v1"
        assert config.model == "gpt-4o-mini"
        assert config.api_key == "sk-test"

    @patch("app.core.llm_loader.SessionLocal")
    def test_user_not_found_raises(self, mock_session_local):
        mock_db = MagicMock()
        mock_db.get.return_value = None
        mock_session_local.return_value = mock_db

        with pytest.raises(LLMConfigError, match="no encontrado"):
            load_user_llm_config(99)

    @patch("app.core.llm_loader.SessionLocal")
    def test_missing_base_url_raises(self, mock_session_local):
        user = FakeUser(user_id=1, base_url=None, model="gpt-4o", encrypted_api_key="x")
        mock_db = MagicMock()
        mock_db.get.return_value = user
        mock_session_local.return_value = mock_db

        with pytest.raises(LLMConfigError, match="URL base"):
            load_user_llm_config(1)

    @patch("app.core.llm_loader.SessionLocal")
    def test_missing_model_loads_empty_model_for_wizard_flow(self, mock_session_local):
        from app.core.encryption import encrypt

        user = FakeUser(
            user_id=1,
            base_url="https://x.com",
            model=None,
            encrypted_api_key=encrypt("sk-test"),
        )
        mock_db = MagicMock()
        mock_db.get.return_value = user
        mock_session_local.return_value = mock_db

        config = load_user_llm_config(1)

        assert config.model == ""

    @patch("app.core.llm_loader.SessionLocal")
    def test_missing_api_key_raises(self, mock_session_local):
        user = FakeUser(
            user_id=1, base_url="https://x.com", model="gpt-4o", encrypted_api_key=None
        )
        mock_db = MagicMock()
        mock_db.get.return_value = user
        mock_session_local.return_value = mock_db

        with pytest.raises(LLMConfigError, match="no tiene API key"):
            load_user_llm_config(1)

    @patch("app.core.llm_loader.SessionLocal")
    def test_corrupted_api_key_raises(self, mock_session_local):
        """Si la API key está corrupta (no se puede desencriptar)."""
        user = FakeUser(
            user_id=1,
            base_url="https://x.com",
            model="gpt-4o",
            encrypted_api_key="dato-corrupto-no-valido",
        )
        mock_db = MagicMock()
        mock_db.get.return_value = user
        mock_session_local.return_value = mock_db

        with pytest.raises(LLMConfigError, match="desencriptar"):
            load_user_llm_config(1)


class TestSaveUserLLMConfig:
    """Tests de save_user_llm_config."""

    @patch("app.core.llm_loader.SessionLocal")
    def test_saves_encrypted_key(self, mock_session_local):
        mock_db = MagicMock()
        mock_user = FakeUser(user_id=1)
        mock_db.get.return_value = mock_user
        mock_session_local.return_value = mock_db

        save_user_llm_config(
            user_id=1,
            base_url="https://api.openai.com/v1",
            model="gpt-4o-mini",
            api_key="sk-my-secret-key",
        )

        assert mock_user.llm_base_url == "https://api.openai.com/v1"
        assert mock_user.llm_model == "gpt-4o-mini"
        # La API key debe estar encriptada, NO en plano
        assert mock_user.encrypted_api_key != "sk-my-secret-key"
        # Pero debe poder desencriptarse al valor original
        from app.core.encryption import decrypt
        assert decrypt(mock_user.encrypted_api_key) == "sk-my-secret-key"
        mock_db.commit.assert_called_once()

    @patch("app.core.llm_loader.SessionLocal")
    def test_user_not_found_raises_on_save(self, mock_session_local):
        mock_db = MagicMock()
        mock_db.get.return_value = None
        mock_session_local.return_value = mock_db

        with pytest.raises(LLMConfigError, match="no encontrado"):
            save_user_llm_config(
                user_id=99, base_url="x", model="x", api_key="x"
            )


class TestBuildLangchainModel:
    """Tests de build_langchain_model."""

    @patch("app.core.llm_loader.init_chat_model")
    @patch("app.core.llm_loader.load_user_llm_config")
    def test_builds_model_with_user_config(self, mock_load, mock_init):
        from app.core.llm_loader import UserLLMConfig

        config = UserLLMConfig(
            user_id=1,
            base_url="https://api.openai.com/v1",
            model="gpt-4o-mini",
            api_key="sk-test",
        )
        mock_load.return_value = config
        mock_model = MagicMock()
        mock_init.return_value = mock_model

        result = build_langchain_model(1)

        mock_init.assert_called_once_with(
            model="gpt-4o-mini",
            model_provider="openai",
            base_url="https://api.openai.com/v1",
            api_key="sk-test",
        )
        assert result == mock_model

    @patch("app.core.llm_loader.init_chat_model")
    @patch("app.core.llm_loader.load_user_llm_config")
    def test_uses_cache_on_second_call(self, mock_load, mock_init):
        from app.core.llm_loader import UserLLMConfig

        config = UserLLMConfig(
            user_id=1,
            base_url="https://api.openai.com/v1",
            model="gpt-4o-mini",
            api_key="sk-test",
        )
        mock_load.return_value = config
        mock_init.return_value = MagicMock()

        # Primera llamada: carga desde DB
        build_langchain_model(1)
        assert mock_load.call_count == 1

        # Segunda llamada: usa cache
        build_langchain_model(1)
        assert mock_load.call_count == 1  # sigue en 1, no recargó

    @patch("app.core.llm_loader.init_chat_model")
    @patch("app.core.llm_loader.load_user_llm_config")
    def test_force_reload_bypasses_cache(self, mock_load, mock_init):
        from app.core.llm_loader import UserLLMConfig

        config = UserLLMConfig(
            user_id=1,
            base_url="https://x.com",
            model="gpt-4o",
            api_key="sk-test",
        )
        mock_load.return_value = config
        mock_init.return_value = MagicMock()

        build_langchain_model(1)
        build_langchain_model(1, force_reload=True)

        assert mock_load.call_count == 2

    @patch("app.core.llm_loader.load_user_llm_config")
    def test_no_config_raises(self, mock_load):
        mock_load.side_effect = LLMConfigError("Usuario sin config")
        with pytest.raises(LLMConfigError, match="sin config"):
            build_langchain_model(1)

    @patch("app.core.llm_loader.load_user_llm_config")
    def test_missing_model_raises_when_building_model(self, mock_load):
        from app.core.llm_loader import UserLLMConfig

        mock_load.return_value = UserLLMConfig(
            user_id=1,
            base_url="https://api.openai.com/v1",
            model="",
            api_key="sk-test",
        )

        with pytest.raises(LLMConfigError, match="paso 3"):
            build_langchain_model(1)


class TestClearSessionCache:
    """Tests de clear_session_cache."""

    @patch("app.core.llm_loader.init_chat_model")
    @patch("app.core.llm_loader.load_user_llm_config")
    def test_clear_specific_user(self, mock_load, mock_init):
        from app.core.llm_loader import UserLLMConfig

        config = UserLLMConfig(
            user_id=1, base_url="x", model="m", api_key="k"
        )
        mock_load.return_value = config
        mock_init.return_value = MagicMock()

        # Cargar 2 usuarios
        mock_load.return_value = UserLLMConfig(
            user_id=2, base_url="x", model="m", api_key="k"
        )
        build_langchain_model(2)
        mock_load.return_value = config
        build_langchain_model(1)

        # Limpiar solo user 1
        clear_session_cache(user_id=1)
        # Próxima llamada a user 1 debe recargar
        build_langchain_model(1)
        assert mock_load.call_count == 3
