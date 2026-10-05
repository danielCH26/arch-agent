"""Tests del LLM default del backend (#98).

Cubre el fallback en `load_user_llm_config`: cuando el usuario no tiene
config LLM, el backend usa `openai/gpt-oss-120b` via Groq con la
`GROQ_API_KEY` del entorno. Si la key no esta, se mantiene el error de antes.

La regla que gobierna todos estos tests: **la config del usuario siempre gana
sobre el default**. El default es el ultimo recurso, no el primero.
"""

import pytest
from unittest.mock import patch

from app.core.llm_loader import (
    DEFAULT_LLM_BASE_URL,
    DEFAULT_LLM_MODEL,
    LLMConfigError,
    load_user_llm_config,
)


class _FakeUser:
    """Usuario minimo, con los tres campos de config que mira el loader."""

    def __init__(self, base_url=None, encrypted_key=None, model=None):
        self.id = 1
        self.llm_base_url = base_url
        self.encrypted_api_key = encrypted_key
        self.llm_model = model


def _patch_user(monkeypatch, user):
    """Parchea la sesion de DB para que devuelva `user` sin tocar Postgres."""
    from app.core import llm_loader

    class _Result:
        def get(self, _model, _user_id):
            return user

        def close(self):
            pass

    class _Session:
        def get(self, _model, _user_id):
            return user

        def close(self):
            pass

    monkeypatch.setattr(llm_loader, "SessionLocal", lambda: _Session())


class TestConstantesDelDefault:
    """El default no es configurable: son constantes."""

    def test_base_url_es_la_de_groq(self):
        assert DEFAULT_LLM_BASE_URL == "https://api.groq.com/openai/v1"

    def test_modelo_es_gpt_oss_120b(self):
        # Production, no Preview. Ver la nota de descarte de qwen3.8-27b en #98.
        assert DEFAULT_LLM_MODEL == "openai/gpt-oss-120b"

    def test_el_default_no_viene_del_entorno(self):
        """La URL del default es constante, no se overridea por env.

        Si fuera configurable, alguien la podria apuntar a cualquier endpoint
        y el default del sistema dejaria de ser un default.
        """
        import os

        original = os.environ.get("LLM_BASE_URL")
        os.environ["LLM_BASE_URL"] = "https://evil.example.com/v1"
        try:
            assert DEFAULT_LLM_BASE_URL == "https://api.groq.com/openai/v1"
        finally:
            if original is None:
                os.environ.pop("LLM_BASE_URL", None)
            else:
                os.environ["LLM_BASE_URL"] = original


class TestFallbackAlDefault:
    """Sin config de usuario + key en entorno => default."""

    def test_usuario_sin_base_url_usa_el_default(self, monkeypatch):
        _patch_user(monkeypatch, _FakeUser())
        monkeypatch.setenv("GROQ_API_KEY", "gsk_test_default")

        config = load_user_llm_config(user_id=1)

        assert config.base_url == DEFAULT_LLM_BASE_URL
        assert config.model == DEFAULT_LLM_MODEL
        assert config.api_key == "gsk_test_default"

    def test_usuario_con_base_url_pero_sin_modelo_no_carga_default(self, monkeypatch):
        """Tiene base_url y key, pero no completo el step3: NO se mezcla con el default.

        Antes del fix (B3), la app devolvia ``UserLLMConfig(base_url=user.llm_base_url,
        model=default.model, ...)``: el endpoint y la key son del usuario pero
        el modelo es el del backend (Groq). Eso produce un 400 silencioso
        cuando el user eligio, por ejemplo, OpenAI como provider: Groq recibe
        un modelo que el no conoce y rechaza el primer request.

        El comportamiento correcto es pedirle al usuario que complete el paso 3
        antes de seguir. La excepcion ``reason="missing"`` es la misma que ya
        lanza ``_init_model`` mas adelante, asi el caller no necesita branches
        adicionales.
        """
        _patch_user(
            monkeypatch,
            _FakeUser(base_url="https://api.openai.com/v1", encrypted_key="enc"),
        )
        monkeypatch.setenv("GROQ_API_KEY", "gsk_test_default")
        monkeypatch.setattr(
            "app.core.llm_loader.decrypt", lambda _x: "sk-user-real"
        )

        with pytest.raises(LLMConfigError) as exc:
            load_user_llm_config(user_id=1)

        assert exc.value.reason == "missing"
        assert "paso" in str(exc.value).lower() and "3" in str(exc.value)

    @pytest.mark.parametrize(
        "base_url",
        [
            # OpenAI: el caso reportado en el review (Groq recibe un modelo
            # que no es suyo y devuelve 400 al primer token).
            "https://api.openai.com/v1",
            # Ollama local: el caso opuesto, el endpoint NO sabe hablar con
            # un id de Groq.
            "http://localhost:11434/v1",
        ],
    )
    def test_base_url_del_usuario_no_se_combina_con_modelo_del_default(
        self, monkeypatch, base_url
    ):
        """Triangulacion sobre distintos endpoints: el modelo del default
        NUNCA termina pegado al endpoint del usuario, en ninguna combinacion.
        """
        _patch_user(
            monkeypatch,
            _FakeUser(base_url=base_url, encrypted_key="enc"),
        )
        monkeypatch.setenv("GROQ_API_KEY", "gsk_test_default")
        monkeypatch.setattr(
            "app.core.llm_loader.decrypt", lambda _x: "sk-user-real"
        )

        with pytest.raises(LLMConfigError) as exc:
            load_user_llm_config(user_id=1)

        assert exc.value.reason == "missing"

    def test_el_default_marca_su_origen(self, monkeypatch):
        """Sin esto no se puede auditar cuanto trafico va por la key del sistema."""
        _patch_user(monkeypatch, _FakeUser())
        monkeypatch.setenv("GROQ_API_KEY", "gsk_test_default")

        config = load_user_llm_config(user_id=1)

        assert config.source == "system_default"

    def test_usuario_con_todo_marca_origen_usuario(self, monkeypatch):
        _patch_user(
            monkeypatch,
            _FakeUser(
                base_url="https://api.openai.com/v1",
                encrypted_key="enc",
                model="gpt-4o-mini",
            ),
        )
        monkeypatch.setattr(
            "app.core.llm_loader.decrypt", lambda _x: "sk-user-real"
        )

        config = load_user_llm_config(user_id=1)

        assert config.source == "user"
        assert config.model == "gpt-4o-mini"


class TestPrioridadDelUsuario:
    """La config propia gana siempre, aunque exista GROQ_API_KEY."""

    def test_key_del_entorno_no_pisa_la_del_usuario(self, monkeypatch):
        _patch_user(
            monkeypatch,
            _FakeUser(
                base_url="https://api.openai.com/v1",
                encrypted_key="enc",
                model="gpt-4o-mini",
            ),
        )
        monkeypatch.setenv("GROQ_API_KEY", "gsk_test_default")
        monkeypatch.setattr(
            "app.core.llm_loader.decrypt", lambda _x: "sk-user-real"
        )

        config = load_user_llm_config(user_id=1)

        assert config.api_key == "sk-user-real"
        assert config.base_url == "https://api.openai.com/v1"
        assert config.model == "gpt-4o-mini"
        assert config.source == "user"


class TestSinKeyDeEntorno:
    """Sin GROQ_API_KEY se mantiene el error, con las dos causas explicadas."""

    def test_usuario_sin_config_y_sin_key_falla(self, monkeypatch):
        _patch_user(monkeypatch, _FakeUser())
        monkeypatch.delenv("GROQ_API_KEY", raising=False)

        with pytest.raises(LLMConfigError) as exc:
            load_user_llm_config(user_id=1)

        # El mensaje tiene que cubrir las DOS causas, no solo la primera:
        # o el usuario configuro su LLM, o el operador configuro el default.
        message = str(exc.value)
        assert "wizard" in message.lower()
        assert "GROQ_API_KEY" in message

    def test_key_vacia_se_trata_como_ausente(self, monkeypatch):
        """`GROQ_API_KEY=""` no es una key: es un default sin credencial."""
        _patch_user(monkeypatch, _FakeUser())
        monkeypatch.setenv("GROQ_API_KEY", "")

        with pytest.raises(LLMConfigError):
            load_user_llm_config(user_id=1)

    def test_key_con_espacios_se_trata_como_ausente(self, monkeypatch):
        _patch_user(monkeypatch, _FakeUser())
        monkeypatch.setenv("GROQ_API_KEY", "   ")

        with pytest.raises(LLMConfigError):
            load_user_llm_config(user_id=1)

    def test_la_key_nunca_aparece_en_el_log(self, monkeypatch, caplog):
        """El log de construccion lleva origen, modelo y base_url. Nunca la key.

        Este log se manda a un agregador, asi que la key del operador no puede
        aparecer ni por error de formato.

        El log vive en `build_langchain_model` (no en el loader), asi que el
        test pasa por ahi: es el punto donde se construye el modelo de verdad.
        """
        import logging

        _patch_user(monkeypatch, _FakeUser())
        monkeypatch.setenv("GROQ_API_KEY", "gsk_secreto_no_debe_aparecer")
        monkeypatch.setattr(
            "app.core.llm_loader._init_model", lambda _config: "model-fake"
        )

        from app.core.llm_loader import build_langchain_model

        with caplog.at_level(logging.INFO, logger="app.core.llm_loader"):
            result = build_langchain_model(user_id=1, force_reload=True)

        assert result == "model-fake"
        assert "gsk_secreto_no_debe_aparecer" not in caplog.text
        # Y el origen si tiene que estar, que es el punto del log.
        assert "system_default" in caplog.text
        assert DEFAULT_LLM_MODEL in caplog.text

    def test_el_log_no_expone_la_key_del_usuario(self, monkeypatch, caplog):
        """Mismo contrato cuando la key es del usuario, no del sistema."""
        import logging

        _patch_user(
            monkeypatch,
            _FakeUser(
                base_url="https://api.openai.com/v1",
                encrypted_key="enc",
                model="gpt-4o-mini",
            ),
        )
        monkeypatch.setattr(
            "app.core.llm_loader.decrypt", lambda _x: "sk-user-secreto"
        )
        monkeypatch.setattr(
            "app.core.llm_loader._init_model", lambda _config: "model-fake"
        )

        from app.core.llm_loader import build_langchain_model

        with caplog.at_level(logging.INFO, logger="app.core.llm_loader"):
            build_langchain_model(user_id=1, force_reload=True)

        assert "sk-user-secreto" not in caplog.text
        assert "source=user" in caplog.text


class TestUsuarioDesconocido:
    def test_usuario_inexistente_no_cae_al_default(self, monkeypatch):
        """Un id invalido es un bug o un ataque, no 'usuario sin configurar'.

        Darle el default a un user_id que no existe en la DB abriria la puerta
        a que cualquier id desbordado reciba el LLM del sistema.
        """
        from app.core import llm_loader

        class _Session:
            def get(self, _model, _user_id):
                return None

            def close(self):
                pass

        monkeypatch.setattr(llm_loader, "SessionLocal", lambda: _Session())
        monkeypatch.setenv("GROQ_API_KEY", "gsk_test_default")

        with pytest.raises(LLMConfigError):
            load_user_llm_config(user_id=999)


class TestAllowDefault:
    """El parametro ``allow_default=False`` lo usan los endpoints del wizard.

    Sin default el endpoint responde 404 con "Completá los pasos 1 y 2".
    Con default, el chat flow recibe el LLM del sistema y la app sigue.
    """

    def test_allow_default_false_no_cae_al_default_sin_config(
        self, monkeypatch
    ):
        """Usuario sin config + GROQ_API_KEY presente => NO devuelve el default."""
        _patch_user(monkeypatch, _FakeUser())
        monkeypatch.setenv("GROQ_API_KEY", "gsk_test_default")

        with pytest.raises(LLMConfigError) as exc:
            load_user_llm_config(user_id=1, allow_default=False)

        assert exc.value.reason == "not_configured"

    def test_allow_default_true_sigue_cayendo_al_default_sin_config(
        self, monkeypatch
    ):
        """El default sigue siendo el ultimo recurso para el chat flow."""
        _patch_user(monkeypatch, _FakeUser())
        monkeypatch.setenv("GROQ_API_KEY", "gsk_test_default")

        config = load_user_llm_config(user_id=1, allow_default=True)

        assert config.source == "system_default"
        assert config.api_key == "gsk_test_default"
