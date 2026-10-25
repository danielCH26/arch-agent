# Golden set de propuestas de arquitectura

Mide cuánta variabilidad hay **de verdad** entre dos ejecuciones idénticas del
generador de propuestas.

La pregunta que responde: *¿el mismo caso, enviado dos veces al mismo modelo,
produce la misma propuesta?* Producción manda la temperatura de
`llm_temperature()` (`app/core/llm_loader.py`, desde #106): `LLM_TEMPERATURE`
si es válida, si no `DEFAULT_LLM_TEMPERATURE` (0.0). El runner usa la misma
regla cuando no se pasa `--temperature`, y registra el valor y su origen en la
metadata (`temperature_solicitada`, `temperature_origen`). Lo que queda por
medir es cuánta dispersión sobrevive a temperatura 0 y cuánta agrega subirla. Ver [Limitaciones honestas](#limitaciones-honestas).

El corpus es **hermético**: `cases.yaml` trae las citations congeladas, así que
no hace falta base de datos, PGVector ni el modelo de embeddings corriendo. Sí
hace falta el entorno Python del backend (`pip install -r requirements.txt`):
el harness importa el prompt real desde `app.core.proposal_generator`, y ese
módulo arrastra `database.py` (crea el engine al importar, sin conectarse),
`rag` y `llm_loader`. Esto vale también para CI.

## Path rápido

1. Validar el corpus y armar el prompt de cada caso, sin red y sin API key:
   ```bash
   python -m evals.runner --dry-run
   ```
2. Configurar el proveedor. Con el default de la app (Groq) alcanza con la
   misma variable que usa producción:
   ```bash
   export GROQ_API_KEY="gsk_..."
   ```
   Para otro proveedor OpenAI-compatible:
   ```bash
   export LLM_BASE_URL="https://api.openai.com/v1"
   export LLM_API_KEY="sk-..."
   export LLM_MODEL="gpt-4o-mini"
   ```
3. Correr la medición (11 casos × 3 repeats = 33 llamadas):
   ```bash
   python -m evals.runner
   ```
4. Leer el resumen que se imprime y el detalle completo en
   `evals/results/<timestamp>.json`.

| Variable | Default | Notas |
|----------|---------|-------|
| `LLM_API_KEY` | — | Obligatoria salvo con el endpoint default, donde cae a `GROQ_API_KEY` |
| `LLM_BASE_URL` | `DEFAULT_LLM_BASE_URL` (`https://api.groq.com/openai/v1`) | |
| `LLM_MODEL` | `DEFAULT_LLM_MODEL` (`openai/gpt-oss-120b`) | Se ignora si se pasa `--models` |

`GROQ_API_KEY` nunca se manda a un endpoint que no sea el de Groq: contra otro
`LLM_BASE_URL` hace falta `LLM_API_KEY` explícita.

## Uso

```bash
# Comparar dos modelos en la misma corrida (ids exactos de Groq)
python -m evals.runner --models openai/gpt-oss-120b,llama-3.3-70b-versatile --repeats 5

# Separar serving de sampling
python -m evals.runner --temperature 1.0 --repeats 5

# Solo algunos casos, sin espera entre llamadas (útil con paid tier)
python -m evals.runner --case hex-001 --case iter-001 --sleep 0
```

| Flag | Default | Para qué sirve |
|------|---------|----------------|
| `--models a,b` | `LLM_MODEL` | Compara varios modelos. Ids exactos del proveedor: en Groq es `openai/gpt-oss-120b`, no `gpt-oss-120b` |
| `--repeats N` | `3` | Repeticiones por caso. Mínimo 2: con 1 no hay pares que comparar |
| `--temperature T` | `LLM_TEMPERATURE` (o `0.0` si no está definida o es inválida) | Temperatura solicitada. La serie `o*` la ignora (ver metadata) |
| `--sleep S` | `2.2` | Segundos entre llamadas. El free tier de Groq son 30 RPM |
| `--retries N` | `2` | Reintentos ante 429, con backoff exponencial |
| `--min-ok-rate F` | `0.9` | Fracción mínima de invocaciones exitosas para salir con 0 |
| `--no-stream-usage` | — | No pedir el uso de tokens en el stream, para proveedores que no lo soportan |
| `--case ID` | todos | Ejecuta solo esos casos. Repetible. Un id inexistente sale con 2 |
| `--output-dir DIR` | `evals/results/` | Dónde escribir el JSON |
| `--dry-run` | — | Valida el corpus y arma los prompts. No llama a la API |

### Orden y fallos

Las invocaciones van **intercaladas** (repeat → caso → modelo): los repeats de
un mismo caso quedan separados por el resto del corpus, para no medirlos todos
en los mismos segundos y bajo las mismas condiciones de serving.

La llamada usa `stream`, igual que `generate_stream` en producción, y concatena
el contenido de los chunks de la misma forma. Un 429 se reintenta con backoff
(`--retries`); otros errores (timeout, 500) se registran y la corrida sigue.
**Una salida vacía cuenta como fallo**, no como éxito: se guarda su
`finish_reason` (`length` indica que un modelo de razonamiento agotó el
presupuesto de tokens) y su `usage`.

### Exit codes

| Código | Significado |
|--------|-------------|
| `0` | Midió y pasó el gate |
| `1` | La corrida no vale como medición: algún modelo no se pudo construir, la tasa de éxito quedó por debajo de `--min-ok-rate`, o ningún par (caso, modelo) tuvo 2 repeats exitosos. El motivo se imprime al final y queda en `gate` del JSON |
| `2` | Error de uso o de configuración (flags, API key, `--case` inexistente) |

El gate dice si la corrida **midió**, no si el modelo es bueno: no hay umbral
de `struct_ok` ni de `exacta`. La puerta de calidad sin costo (`--dry-run` más
`pytest evals/test_runner.py`) corre en el job de backend de
`.github/workflows/ci.yml`.

### El contrato es el de producción

El scorer **no** mantiene su propia lista de secciones obligatorias: importa
`_REQUIRED_HEADINGS` y juzga con `_missing_sections` de
`app/core/proposal_generator.py`, con los mismos argumentos que
`generate_stream` (`source_count=len(citations)`: con fuentes, la tabla de
trade-offs tiene que citarlas como `[n]` distintos). Antes el harness llevaba una copia local (3
secciones, "Tecnologías" con tilde y comparación sin normalizar acentos) que
se desincronizó del prompt: cualquier propuesta válida de producción se
medía como fallida. Ahora, si producción cambia el contrato, el scorer lo
sigue sin tocar el harness.

## Qué mide cada métrica

El scorer (`score_output`) es puro: sin red, sin DB, sin LLM. Verifica el
contrato de formato del prompt de producción. Una salida tiene
`pass_estructural=True` si cumple las seis condiciones:

1. `secciones_ok`: `_missing_sections` de producción no reporta nada. Es
   decir, están las cinco secciones (Componentes, Tecnologias, Patrones,
   Justificación del patrón principal, Trade-offs y decisión), en cualquier
   nivel de encabezado y sin distinguir acentos, mayúsculas, plural,
   numeración ni negritas; la justificación llega al riesgo o costo; la tabla
   de trade-offs tiene 3 opciones y 3 criterios y, si hubo citations, cita
   `min(n, 3)` fuentes `[n]` distintas; y hay recomendación y punto de
   decisión. Lo que falta queda en `secciones_faltantes`.
2. `orden_ok`: las cinco secciones en ese orden.
3. `sin_secciones_extra`: ningún `#` (H1) ni `##` que no sea una sección
   obligatoria. Los subtítulos `###` dentro de una sección se permiten.
4. `sin_preambulo`: nada antes de la primera sección. El prompt pide responder
   "exactamente" con las cinco secciones.
5. `citas_validas`: todo marcador cae dentro de las citations provistas. Se
   reconocen `[1]`, `[1, 2]` y `[1-3]`; con `citations: []` cualquier marcador
   es inválido.
6. `sin_corte`: `finish_reason` no es `"length"`. Producción descarta esa
   propuesta aunque tenga todas las secciones.

Si el scorer fallara con una salida rara, la ejecución queda como fallida
(`error del scorer: ...`, con el markdown guardado) y la corrida sigue: nunca se
pierde el JSON de una corrida por una excepción del scorer.

El código (bloques cercados y `inline`) se ignora: un `## Algo` o un `arr[0]`
dentro de un bloque no es un encabezado ni una cita. Excepción: el veredicto
de `secciones_ok` es el de producción, que no ignora el código; si una sección
solo aparece dentro de un bloque, `secciones_ok` puede dar `True` pero
`orden_ok` da `False` (no tiene posición real). `cierre_suelto` (la última
línea no es un bullet, p. ej. "Espero que te sirva") se reporta pero no entra
al pass, porque un párrafo final legítimo también lo dispara.
`bullets_por_seccion` cuenta `-`, `*`, `+`, `•` y `1.`; es informativo y queda
en el JSON.

Por cada par (caso, modelo), sobre los repeats exitosos:

| Métrica | Qué es | Cómo interpretarla |
|---------|--------|--------------------|
| `tasa_exacta` | Fracción de pares de repeats idénticos byte a byte | `1.00` = reproducible. Frágil: un espacio de más cuenta como distinto |
| `tasa_exacta_normalizada` | Ídem, ignorando espacios al final de línea y líneas vacías repetidas | Si sube mucho respecto de `tasa_exacta`, la diferencia es de espacios |
| `salidas_distintas` | Cantidad de textos distintos entre los repeats | `1` = todos iguales; `n` = todos distintos |
| `similitud_media` | Similitud media entre pares (`difflib`, 0 a 1) | Graduada: distingue "cambió una palabra" de "es otra propuesta" |
| `acuerdo_estructural` | Fracción de pares con el mismo `pass_estructural` | Consistencia del formato. **Alto no es bueno por sí solo**: ver abajo |
| `solapamiento_citas` | Jaccard medio de los marcadores entre pares | Si el modelo cita los mismos patrones en cada corrida |
| `desvio_largo` | Desviación estándar del largo, en caracteres | Estabilidad del volumen de texto |
| `tasa_pass_estructural` | Fracción de salidas con `pass_estructural` | Cumplimiento del contrato |

Todas las métricas de pares quedan en `null` (`n/d` en la tabla) con menos de
**dos** repeats exitosos. El resumen por modelo promedia **solo los casos
medibles** (columna `medib`), y la columna `ok` muestra exitosas/planeadas para
que un `struct_ok 1.000` sobre 1 de 30 no pase por buena noticia.

### Cómo se leen juntas

- **`acuerdo_estructural` alto**: el formato es consistente, pero puede ser
  consistente en fallar. La línea "N casos pasan siempre, M fallan siempre"
  bajo cada modelo dice cuál de las dos es.
- **`tasa_exacta` baja con `similitud_media` alta**: el modelo dice lo mismo
  con otras palabras. No sirve diffear propuestas, pero el contenido es estable.
- **`similitud_media` baja**: cada repeat es otra propuesta. Ahí sí hay un
  problema de reproducibilidad de fondo.
- **`solapamiento_citas` bajo**: cita patrones distintos en cada corrida. Es la
  métrica que más pesa si la propuesta hay que respaldarla. Ojo: dos salidas
  sin ninguna cita dan 1.0.

## Limitaciones honestas

1. **Con `temperature 0` la variabilidad restante no es de sampling, es de
   serving.** Es la Expected Batch Invariance: el orden de los requests en el
   lote, el hardware y las reducciones en punto flotante cambian el resultado.
   En las corridas de #99, `exacta` a 0.0 dio entre 0.033 y 0.067.
2. **`temperature 0` NO garantiza determinismo.** El proveedor puede no honrar
   el parámetro, o mapearlo distinto. Para la serie `o*` ni siquiera se manda:
   la metadata registra `temperature_efectiva: null` en ese caso.
3. **Los pares no son independientes.** 5 repeats dan 10 pares, pero la
   muestra efectiva sigue siendo 5 salidas por caso, y el harness no calcula
   intervalos. Diferencias chicas entre corridas no son señal: por eso el
   criterio de baselines pide al menos 2 corridas por configuración.
4. **No se mide la variabilidad del RAG.** Las citations están congeladas. En
   producción el recall también varía, y `RAG_MIN_SIMILARITY` es una frontera:
   dos consultas casi iguales pueden caer de un lado o del otro. La
   variabilidad de punta a punta es **mayor o igual** a la que mide el harness.
5. **El prompt se mide sin `requirements_text` ni `documents_text`.** La
   `descripcion` sí entra al prompt, igual que en producción (#112): el runner
   se la pasa a `_build_prompt`. Pero los requisitos y los documentos que en
   producción vienen del proyecto no están en el corpus, así que el harness
   mide el prompt sin ellos. Un proyecto real con requisitos cargados manda un
   prompt más largo y con más contexto que el que se mide acá.
6. **El scorer juzga formato, no calidad.** Detecta secciones faltantes o citas
   fuera de rango. No dice si el consejo de arquitectura es correcto, ni
   verifica que la cita respalde lo que se afirma.

## Cómo agregar un caso

Editá `cases.yaml` y agregá una entrada en `casos`:

```yaml
  - id: nue-001
    nombre: "Nombre legible del escenario"
    project_name: "NombreDeProyecto"
    descripcion: >-
      Contexto como lo escribiría un usuario real: equipo, restricciones,
      plazos, qué duele hoy.
    citations:
      - pattern_name: "Microservicios"
        snippet: "Microservicios: Divide el sistema en ..."   # chunk_text[:240]
    # Opcionales, para el camino de iteración:
    feedback: "Lo que el usuario pide cambiar."
    prior_content: |-
      ## Componentes
      - ...
```

Reglas para que el caso sirva:

- `id` único. El harness lo usa como clave en el JSON de resultados.
- Cada `snippet` es el `chunk_text` real truncado a 240 caracteres, tal como
  lo arma `scripts/seed_patterns.py::seed_pattern_chunks` (tipos `summary`,
  `tradeoffs`, `when_not_to_use`, `decision_signals`). `test_runner.py` lo
  verifica contra el chunker: si editás un patrón en `data/patterns/`, el test
  falla y dice qué snippet regenerar.
- Hasta 5 citations (producción usa `k=5`); repetir un patrón con chunks
  distintos es lo normal.
- Al menos dos casos con `citations: []` para medir qué hace el modelo cuando el
  recuperador no encontró nada (no debería inventar marcadores `[N]`).
- Al menos un caso donde los patrones expuestos **no** apliquen, y al menos uno
  con `feedback` y `prior_content`.

`evals/results/<timestamp>.json` guarda el markdown completo de cada salida, no
solo los scores.

## Qué guarda el JSON

- `metadata.procedencia`: commit de git (y si el árbol estaba sucio), sha256 de
  `cases.yaml`, del código de `_build_prompt` y de cada prompt armado, versión
  de Python y de `langchain`, `langchain-core`, `langchain-openai`, `openai` y
  `pyyaml`, y los argumentos de la corrida.
- `metadata.temperature_solicitada`, `metadata.temperature_origen`
  (`--temperature`, `LLM_TEMPERATURE` o `DEFAULT_LLM_TEMPERATURE`) y
  `metadata.temperature_efectiva` por modelo (`null` = el kwarg se omitió y el
  proveedor usó la suya).
- `gate`: si la corrida pasó y por qué no.
- `errores_construccion`: modelos que no se pudieron construir.
- `ejecuciones`: cada invocación con orden, hora, intentos, latencia,
  `finish_reason`, `usage`, markdown y score.
- `variabilidad` y `resumen_por_modelo`: las métricas de arriba.

## Archivos

| Archivo | Qué hace |
|---------|----------|
| `cases.yaml` | El corpus. Datos estáticos |
| `runner.py` | Scorer puro + runner de ejecución + métricas de variabilidad |
| `test_runner.py` | Tests offline (sin red, sin API key) |
| `baselines/` | Resúmenes versionados de corridas de referencia |
| `results/` | Salidas completas por corrida, una por timestamp (ignorado por git) |

`runner.py` arma el prompt con `app.core.proposal_generator._build_prompt`. El
texto del prompt nunca se copia al harness: si producción cambia el prompt, el
golden set se entera en la corrida siguiente, y el hash del prompt cambia en la
metadata.

## Checklist antes de sacar conclusiones

- [ ] Corriste `--dry-run` y el corpus es válido
- [ ] La corrida salió con exit 0 (pasó el gate)
- [ ] Usaste `--repeats 5` o más (con 3 las diferencias se ven, pero las medias
      son ruidosas)
- [ ] Comparaste `--temperature 0` contra `--temperature 1.0` para separar
      serving de sampling
- [ ] Miraste `similitud_media` y `solapamiento_citas`, no solo `tasa_exacta`
- [ ] Repetiste la corrida en otro horario: si los números cambian mucho entre
      corridas, el servicio tiene variabilidad propia
