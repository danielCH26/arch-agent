"""
Tests para el loader de configuración LLM.

Issue: #7 - HU12 Configuración de LLM
"""

import pytest
from unittest.mock import MagicMock, patch

import asyncio
import logging

from app.core import llm_loader
from app.core.llm_loader import (
    DEFAULT_LLM_TEMPERATURE,
    LLM_MODELS_WITHOUT_TEMPERATURE_ENV,
    LLM_TEMPERATURE_ENV,
    TEMPERATURE_REJECTED_MESSAGE,
    _acepta_temperature,
    ainvoke_with_temperature_fallback,
    astream_with_temperature_fallback,
    explain_llm_error,
    invoke_with_temperature_fallback,
    is_temperature_rejection,
    llm_temperature,
    without_temperature,
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
    llm_loader._modelos_sin_temperature_runtime.clear()
    yield
    clear_session_cache()
    llm_loader._modelos_sin_temperature_runtime.clear()


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
            temperature=DEFAULT_LLM_TEMPERATURE,
        )
        assert result == mock_model

    @patch("app.core.llm_loader.init_chat_model")
    @patch("app.core.llm_loader.load_user_llm_config")
    def test_builds_model_with_zero_temperature(self, mock_load, mock_init):
        """La app debe fijar temperature=0.0 explicito.

        Groq y OpenAI usan 1.0 por defecto (maximo de aleatoriedad). Si
        ``_init_model`` deja de pasar el parametro, produccion vuelve a
        muestrear al maximo en silencio.
        """
        from app.core.llm_loader import UserLLMConfig

        mock_load.return_value = UserLLMConfig(
            user_id=1,
            base_url="https://api.groq.com/openai/v1",
            model="llama-3.3-70b-versatile",
            api_key="gsk-test",
        )
        mock_init.return_value = MagicMock()

        build_langchain_model(1)

        assert mock_init.call_args.kwargs["temperature"] == 0.0
        assert DEFAULT_LLM_TEMPERATURE == 0.0

    @patch("app.core.llm_loader.init_chat_model")
    @patch("app.core.llm_loader.load_user_llm_config")
    def test_temperatura_se_manda_siempre_incluso_con_cache(self, mock_load, mock_init):
        """Tambien en la ruta cacheada: la temperatura no puede quedar de lado."""
        from app.core.llm_loader import UserLLMConfig

        mock_load.return_value = UserLLMConfig(
            user_id=1,
            base_url="https://api.openai.com/v1",
            model="gpt-4o-mini",
            api_key="sk-test",
        )
        mock_init.return_value = MagicMock()

        build_langchain_model(1)
        build_langchain_model(1)  # segunda vez sale del cache de config

        assert mock_init.call_count == 2
        for llamada in mock_init.call_args_list:
            assert llamada.kwargs["temperature"] == 0.0

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


class TestAceptaTemperature:
    """`_acepta_temperature` decide si se manda el kwarg `temperature`.

    Funcion pura: se testea como tabla de entradas/salidas, sin mocks.
    """

    @pytest.mark.parametrize(
        "model",
        [
            "gpt-4o-mini",
            "gpt-4o",
            "gpt-4.1",
            # gpt-5-chat si acepta temperatura (la restriccion es de gpt-5 no-chat).
            "gpt-5-chat-latest",
            "openai/gpt-5-chat-latest",
            "gpt-4.5-preview",
            "llama-3.3-70b-versatile",
            "llama-3.1-8b-instant",
            "openai/gpt-4o-mini",
            "mixtral-8x7b",
            "",
            "   ",
        ],
    )
    def test_familias_comunes_si_aceptan(self, model):
        assert _acepta_temperature(model) is True

    @pytest.mark.parametrize(
        "model",
        [
            # Serie o completa: prefijo `o` + digito de generacion.
            "o1",
            "o1-mini",
            "o1-preview",
            "o1-pro",
            "o3",
            "o3-mini",
            "o3-pro",
            "o4-mini",
            # Bordes: snapshots con fecha, mayusculas y espacios.
            "o1-2024-12-17",
            "o3-mini-2025-01-31",
            "o4-mini-2025-04-16",
            "O1",
            "O1-MINI",
            "  o1-mini  ",
            # Generaciones futuras: la regex no es una lista cerrada.
            "o2",
            "o5",
        ],
    )
    def test_serie_o_no_acepta(self, model):
        assert _acepta_temperature(model) is False

    def test_ningun_modelo_completo_empieza_con_o_mas_digito(self):
        """Evita que el prefijo se coma familias que contienen 'o' o un digito.

        `gpt-4o` tiene una `o`, `llama-3.3` tiene un `3`: ninguno puede
        devolver False por accidente.
        """
        for model in ("gpt-4o", "gpt-4o-mini", "llama-3.3-70b", "qwen2.5"):
            assert _acepta_temperature(model) is True

    @pytest.mark.parametrize(
        "model",
        [
            # Formato `provider/modelo` de gateways OpenAI-compatibles como
            # OpenRouter ("openai/o1-mini"): la regex tiene que reconocer el
            # `o\d` aunque venga precedido de `provider/`.
            "openai/o1-mini",
            "openai/o1",
            "groq/o1",
            "groq/o1-mini",
            "azure/o4-mini",
            "openai/o3-pro",
            "openai/o3",
            # Mayusculas y espacios: la normalizacion debe llegar antes.
            "OpenAI/O1-Mini",
            "  openai/o1-mini  ",
            # Decision deliberada: cualquier provider cuyo segmento despues
            # del slash sea `o\d` omite la temperatura. Un falso positivo es
            # inocuo (se usa el default del provider); un falso negativo es 400.
            "anthropic/o3",
        ],
    )
    def test_serie_o_con_prefijo_de_provider_no_acepta(self, model):
        r"""Con prefijo `provider/`, la regex `(?:^|/)o\d` lo reconoce igual.

        Antes del fix, `_RECHAZA_TEMPERATURE_RE = re.compile(r"^o\d")`
        fallaba con `openai/o1-mini`: sin hacer match, el modelo recibia
        temperature=0 y OpenAI respondia 400.
        """
        assert _acepta_temperature(model) is False

    @pytest.mark.parametrize(
        "model",
        [
            # Aunque arranque con `openai/`, si el token siguiente NO es
            # `o\d` (p.ej. `gpt-4o-mini`), la regex no debe matchear.
            "openai/gpt-4o-mini",
            "groq/llama-3.3-70b-versatile",
            "anthropic/claude-3-opus",
        ],
    )
    def test_provider_prefijado_que_no_es_o_digito_si_acepta(self, model):
        assert _acepta_temperature(model) is True


    @pytest.mark.parametrize(
        "model",
        [
            "gpt-5",
            "gpt-5-mini",
            "gpt-5-nano",
            "gpt-5-pro",
            "gpt-5.1",
            "gpt-5-2025-08-07",
            "GPT-5-MINI",
            # Con prefijo de provider: la guarda de langchain-openai decide con
            # startswith("gpt-5") y NO los cubre, por eso se resuelve en la app.
            "openai/gpt-5",
            "openai/gpt-5-mini",
            "openai/gpt-5-nano",
            "  OpenAI/GPT-5  ",
        ],
    )
    def test_serie_gpt5_no_chat_no_acepta(self, model):
        assert _acepta_temperature(model) is False

    def test_override_por_env_para_nombres_arbitrarios(self, monkeypatch):
        """Un deployment de Azure con nombre libre no lo adivina ninguna regex."""
        assert _acepta_temperature("my-o1-deployment") is True

        monkeypatch.setenv(
            LLM_MODELS_WITHOUT_TEMPERATURE_ENV, " My-O1-Deployment , otro-razonador,"
        )

        assert _acepta_temperature("my-o1-deployment") is False
        assert _acepta_temperature("OTRO-RAZONADOR") is False
        # Lo que no esta listado sigue la regla de siempre.
        assert _acepta_temperature("gpt-4o-mini") is True

    def test_override_por_env_vacio_no_cambia_nada(self, monkeypatch):
        monkeypatch.setenv(LLM_MODELS_WITHOUT_TEMPERATURE_ENV, " , ")
        assert _acepta_temperature("gpt-4o-mini") is True
        assert _acepta_temperature("") is True


_TEMPERATURE_400 = (
    "Error code: 400 - Unsupported value: 'temperature' does not support "
    "0.0 with this model. Only the default (1) value is supported."
)


class TestIsTemperatureRejection:
    def test_400_de_openai(self):
        assert is_temperature_rejection(Exception(_TEMPERATURE_400)) is True

    def test_status_code_400_del_sdk(self):
        exc = Exception("'temperature' must be 1")
        exc.status_code = 400
        assert is_temperature_rejection(exc) is True

    def test_la_palabra_sola_no_alcanza(self):
        # Falso positivo que el chequeo anterior (solo "temperature") aceptaba.
        assert is_temperature_rejection(Exception("timeout leyendo temperature_logs")) is False

    def test_otros_errores(self):
        assert is_temperature_rejection(Exception("Error code: 429 - rate limit")) is False

    def test_recorre_la_cadena_de_causas(self):
        try:
            try:
                raise Exception(_TEMPERATURE_400)
            except Exception as inner:
                raise RuntimeError("La llamada al modelo fallo") from inner
        except RuntimeError as outer:
            assert is_temperature_rejection(outer) is True


class TestExplainLLMError:
    def test_error_de_temperature_da_un_mensaje_para_el_usuario(self, caplog):
        with caplog.at_level(logging.WARNING, logger="app.core.llm_loader"):
            mensaje = explain_llm_error(Exception(_TEMPERATURE_400))
        assert mensaje == TEMPERATURE_REJECTED_MESSAGE
        # El usuario no tiene acceso al .env: la variable va al log, no al mensaje.
        assert LLM_MODELS_WITHOUT_TEMPERATURE_ENV not in mensaje
        assert LLM_MODELS_WITHOUT_TEMPERATURE_ENV in caplog.text
        assert "Only the default (1)" in caplog.text  # detalle del provider, para el operador

    def test_otros_errores_pasan_tal_cual(self):
        assert explain_llm_error(Exception("rate limit")) == "rate limit"


class TestLLMTemperatureEnv:
    def test_sin_env_usa_el_default(self, monkeypatch):
        monkeypatch.delenv(LLM_TEMPERATURE_ENV, raising=False)
        assert llm_temperature() == DEFAULT_LLM_TEMPERATURE

    def test_env_valida_sobrescribe(self, monkeypatch):
        monkeypatch.setenv(LLM_TEMPERATURE_ENV, "0.6")
        assert llm_temperature() == 0.6

    @pytest.mark.parametrize("raw", ["abc", "-0.1", "2.5"])
    def test_env_invalida_vuelve_al_default(self, monkeypatch, raw):
        monkeypatch.setenv(LLM_TEMPERATURE_ENV, raw)
        assert llm_temperature() == DEFAULT_LLM_TEMPERATURE

    @patch("app.core.llm_loader.init_chat_model")
    @patch("app.core.llm_loader.load_user_llm_config")
    def test_init_model_manda_la_temperatura_del_env(self, mock_load, mock_init, monkeypatch):
        from app.core.llm_loader import UserLLMConfig

        monkeypatch.setenv(LLM_TEMPERATURE_ENV, "0.6")
        mock_load.return_value = UserLLMConfig(
            user_id=1, base_url="https://api.groq.com/openai/v1", model="qwen/qwen3-32b", api_key="k"
        )
        mock_init.return_value = MagicMock()
        build_langchain_model(1)
        assert mock_init.call_args.kwargs["temperature"] == 0.6


class _FakeChatModel:
    """Doble minimo de ChatOpenAI: rechaza `temperature` mientras la tenga."""

    def __init__(self, model_name="my-o1-deployment", temperature=0.0, chunks=("a", "b")):
        self.model_name = model_name
        self.temperature = temperature
        self.chunks = chunks

    def model_copy(self, update):
        return _FakeChatModel(self.model_name, update.get("temperature"), self.chunks)

    def _check(self):
        if self.temperature is not None:
            raise Exception(_TEMPERATURE_400)

    def invoke(self, *_args, **_kwargs):
        self._check()
        return "ok"

    async def ainvoke(self, *_args, **_kwargs):
        self._check()
        return "ok"

    async def astream(self, *_args, **_kwargs):
        self._check()
        for chunk in self.chunks:
            yield chunk


def _collect(agen):
    async def _run():
        return [item async for item in agen]

    return asyncio.run(_run())


class TestRetryWithoutTemperature:
    def test_invoke_reintenta_sin_temperature_y_recuerda_el_modelo(self):
        assert invoke_with_temperature_fallback(_FakeChatModel(), ["hola"]) == "ok"
        # El modelo queda recordado: el proximo build ya no manda el parametro.
        assert _acepta_temperature("my-o1-deployment") is False

    def test_ainvoke_reintenta_sin_temperature(self):
        assert asyncio.run(ainvoke_with_temperature_fallback(_FakeChatModel(), "p")) == "ok"

    def test_otros_errores_no_se_reintentan(self):
        model = MagicMock()
        model.invoke.side_effect = Exception("Error code: 429 - rate limit")
        with pytest.raises(Exception, match="429"):
            invoke_with_temperature_fallback(model, ["hola"])
        assert model.invoke.call_count == 1

    def test_sin_temperature_que_quitar_no_hay_reintento(self):
        model = _FakeChatModel(temperature=None)
        assert without_temperature(model, Exception(_TEMPERATURE_400)) is None

    def test_doble_sin_model_copy_no_hay_reintento(self):
        class _SinCopia:
            temperature = 0.0
            model_name = "x"

        assert without_temperature(_SinCopia(), Exception(_TEMPERATURE_400)) is None
        assert _acepta_temperature("x") is True

    @patch("app.core.llm_loader.init_chat_model")
    @patch("app.core.llm_loader.load_user_llm_config")
    def test_despues_del_rechazo_el_build_omite_temperature(self, mock_load, mock_init):
        from app.core.llm_loader import UserLLMConfig

        invoke_with_temperature_fallback(_FakeChatModel(model_name="My-O1-Deployment"), [])
        mock_load.return_value = UserLLMConfig(
            user_id=1, base_url="x", model="my-o1-deployment", api_key="k"
        )
        mock_init.return_value = MagicMock()
        build_langchain_model(1)
        assert "temperature" not in mock_init.call_args.kwargs

    def test_stream_reintenta_antes_de_la_primera_salida(self):
        items = _collect(
            astream_with_temperature_fallback(_FakeChatModel(), lambda m: m.astream("p"))
        )
        assert items == ["a", "b"]

    def test_stream_no_reintenta_despues_de_emitir(self):
        async def _falla_a_mitad(_model):
            yield "a"
            raise Exception(_TEMPERATURE_400)

        with pytest.raises(Exception, match="temperature"):
            _collect(astream_with_temperature_fallback(_FakeChatModel(), _falla_a_mitad))

    def test_stream_ignora_lo_que_no_cuenta_como_salida(self):
        intentos = []

        async def _stream(model):
            intentos.append(model.temperature)
            yield {"event": "degraded"}
            if model.temperature is not None:
                raise Exception(_TEMPERATURE_400)
            yield {"event": "token"}

        items = _collect(
            astream_with_temperature_fallback(
                _FakeChatModel(),
                _stream,
                counts_as_output=lambda ev: ev["event"] == "token",
            )
        )
        assert intentos == [0.0, None]
        assert items[-1] == {"event": "token"}


class TestInitModelTemperature:
    """`_init_model` solo manda `temperature` si el modelo lo acepta."""

    @staticmethod
    def _config(model: str):
        from app.core.llm_loader import UserLLMConfig

        return UserLLMConfig(
            user_id=1,
            base_url="https://api.openai.com/v1",
            model=model,
            api_key="sk-test",
        )

    @pytest.mark.parametrize("model", ["gpt-4o-mini", "llama-3.3-70b"])
    def test_modelo_comun_recibe_temperature_cero(self, model):
        from app.core.llm_loader import _init_model

        with patch("app.core.llm_loader.init_chat_model") as mock_init:
            mock_init.return_value = MagicMock()
            _init_model(self._config(model))

        kwargs = mock_init.call_args.kwargs
        assert kwargs["temperature"] == 0.0
        assert DEFAULT_LLM_TEMPERATURE == 0.0

    @pytest.mark.parametrize(
        "model",
        ["o1", "o1-mini", "o3-mini", "o4-mini", "gpt-5", "openai/gpt-5-mini"],
    )
    def test_modelo_serie_o_no_recibe_temperature(self, model):
        """Sin el kwarg el request sale sin `temperature` (o con 1 para `o1*`).

        Para `o1*` langchain fuerza 1 solo si el kwarg no viene; para `o3*`,
        `o4*` y `gpt-5*` queda en None y la API aplica su default. Mandar 0.0
        explicito llega al request y OpenAI responde 400.
        """
        from app.core.llm_loader import _init_model

        with patch("app.core.llm_loader.init_chat_model") as mock_init:
            mock_init.return_value = MagicMock()
            _init_model(self._config(model))

        kwargs = mock_init.call_args.kwargs
        assert "temperature" not in kwargs
        # El resto de los kwargs no se tocan.
        assert kwargs["model"] == model
        assert kwargs["model_provider"] == "openai"
        assert kwargs["base_url"] == "https://api.openai.com/v1"
        assert kwargs["api_key"] == "sk-test"

    @patch("app.core.llm_loader.load_user_llm_config")
    def test_build_langchain_model_tambien_lo_omite_para_serie_o(self, mock_load):
        """La regla aplica en la ruta cacheada y en la fresca, por igual."""
        mock_load.return_value = self._config("o1-mini")

        with patch("app.core.llm_loader.init_chat_model") as mock_init:
            mock_init.return_value = MagicMock()
            build_langchain_model(1)
            build_langchain_model(1)

        assert mock_init.call_count == 2
        for llamada in mock_init.call_args_list:
            assert "temperature" not in llamada.kwargs


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
