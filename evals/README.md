# Golden set de propuestas de arquitectura

Mide cuánta variabilidad hay **de verdad** entre dos ejecuciones idénticas del
generador de propuestas, antes de decidir cualquier migración de proveedor.

La pregunta que responde: *¿el mismo caso, enviado dos veces al mismo modelo,
produce la misma propuesta?* Si la respuesta es no, el problema no es el
proveedor: es que la app hoy no declara `temperature` y corre con el default del
proveedor (1.0 en Groq y OpenAI, el máximo de aleatoriedad). Ver
[Hallazgo de fondo](#hallazgo-de-fondo-la-app-no-setea-temperature).

El corpus es **hermético**: `cases.yaml` trae las citations escritas a mano, así
que corre en una laptop con una sola API key. Sin base de datos, sin PGVector,
sin modelo de embeddings.

## Path rápido

1. Validar el corpus, sin red y sin API key:
   ```bash
   python -m evals.runner --dry-run
   ```
2. Configurar el proveedor (ejemplo con Groq):
   ```bash
   export LLM_BASE_URL="https://api.groq.com/openai/v1"
   export LLM_API_KEY="gsk_..."
   export LLM_MODEL="openai/gpt-oss-120b"
   ```
3. Correr la medición (10 casos × 3 repeats = 30 llamadas):
   ```bash
   python -m evals.runner
   ```
4. Leer el resumen que se imprime y el detalle completo en
   `evals/results/<timestamp>.json`.

Sin API key, el paso 1 igual funciona: es la puerta de calidad de CI.

## Uso

```bash
# Comparar dos modelos en la misma corrida
python -m evals.runner --models gpt-oss-120b,llama-3.3-70b-versatile --repeats 5

# Reproducir la variabilidad con sampling real, no solo con serving
python -m evals.runner --temperature 1.0 --repeats 10

# Solo algunos casos, sin espera entre llamadas (útil con paid tier)
python -m evals.runner --case hex-001 --case cpl-001 --sleep 0
```

| Flag | Default | Para qué sirve |
|------|---------|----------------|
| `--models a,b` | `LLM_MODEL` | Compara varios modelos en la misma corrida |
| `--repeats N` | `3` | Repeticiones del mismo caso, para medir variabilidad |
| `--temperature T` | `0.0` | Temperatura de muestreo. Declarada a propósito (ver abajo) |
| `--sleep S` | `2.2` | Segundos entre llamadas. El free tier de Groq son 30 RPM |
| `--case ID` | todos | Ejecuta solo esos casos. Repetible |
| `--dry-run` | — | Valida el corpus. No llama a la API |

Un caso que falla (429, timeout, 500) se registra y la corrida sigue. Un 429
además dispara un backoff para no encadenar el rate limit.

## Qué mide cada métrica

El scorer (`score_output`) es puro: sin red, sin DB, sin LLM. Verifica que la
salida cumpla el contrato de formato que exige el prompt de producción
(`## Componentes`, `## Tecnologías`, `## Patrones`, en ese orden, sin secciones
extra, con citas dentro de rango).

| Métrica | Qué es | Cómo interpretarla |
|---------|--------|--------------------|
| `tasa_exacta` | Fracción de pares de repeats idénticos byte a byte | `1.00` = totalmente reproducible. `0.00` = cada repeat es distinto |
| `acuerdo_estructural` | Fracción de pares con el mismo `pass_estructural` | Mide si el modelo cumple el **formato** de forma consistente |
| `solapamiento_citas` | Jaccard medio de los marcadores `[N]` entre pares | Mide si el modelo **cita los mismos patrones** en cada corrida |
| `desvio_largo` | Desviación estándar del largo, en caracteres | Mide la estabilidad del volumen de texto |
| `pass_estructural` | Las 4 condiciones anteriores juntas | `True`/`False` por salida |

### Cómo se leen juntas

Las dos primeras páginas de la tabla dicen cosas distintas, y la diferencia es
el hallazgo operativo:

- **`tasa_exacta` baja pero `acuerdo_estructural` alta** → el modelo es estable en
  la *forma* pero variable en la *palabra*. La propuesta siempre tiene las tres
  secciones en orden, pero el texto cambia en cada corrida. Conclusión: no
  sirve diffear propuestas ni leer dos veces esperando lo mismo, pero sí se puede
  confiar en la estructura.
- **`tasa_exacta` alta** → el modelo es reproducible en ese caso. Suele ser el
  caso en RAG vacío o en proyectos con una respuesta obvia.
- **`solapamiento_citas` bajo** → el modelo cita patrones distintos en cada
  corrida. Es la métrica que más pesa si a la propuesta hay que respaldarla: la
  trazabilidad no es reproducible aunque la forma sí lo sea.
- **`acuerdo_estructural` bajo** → el modelo no cumple el contrato de forma
  consistente. Es un problema del prompt o del modelo, no del sampling.

`n/d` significa que no se pudo calcular: hizo falta menos de un repeat exitoso.

## Hallazgo de fondo: la app no setea temperature

`app/core/llm_loader.py::_init_model` construye el modelo así:

```python
model = init_chat_model(
    model=config.model,
    model_provider="openai",
    base_url=config.base_url,
    api_key=config.api_key,
)
```

No pasa `temperature`. Cada proveedor aplica su default, y tanto Groq como
OpenAI usan **1.0**: la producción corre con el máximo de muestreo, sin que nadie
lo haya decidido explícitamente.

Por eso el harness exige `--temperature` con default `0.0` y deja la decisión
documentada. Cualquier número que salga de acá es un piso, no un techo: la
variabilidad real de producción es igual o peor.

## Limitaciones honestas

1. **Con `temperature 0` la variabilidad restante no es de sampling, es de
   serving.** Es la Expected Batch Invariance: el orden de los requests en el
   lote, el hardware y las reducciones en punto flotante cambian el resultado.
2. **`temperature 0` NO garantiza determinismo absoluto.** El proveedor puede
   no honrar el parámetro, o mapearlo distinto. Una `tasa_exacta` menor que 1.0
   con `temperature 0` no es un bug del harness: es un hallazgo sobre el
   proveedor, y es exactamente el tipo de dato que justifica (o descarta) una
   migración.
3. **No se mide la variabilidad del RAG.** Las citations están congeladas a
   mano. En producción el recall también varía, y el umbral
   `RAG_MIN_SIMILARITY = 0.85` es una frontera: dos consultas casi iguales pueden
   caer de un lado o del otro. La variabilidad de punta a punta es **mayor o
   igual** a la que mide este harness.
4. **`descripcion` no llega al modelo.** En producción solo alimenta
   `_build_summary_query`, y de ahí llega al prompt únicamente a través de los
   snippets recuperados. Como aquí las citations están congeladas, `descripcion`
   es documental: explica de dónde salió cada caso.
5. **El scorer juzga formato, no calidad.** Detecta que faltan secciones o que
   hay una cita inventada. No puede decirte si el consejo de arquitectura es
   correcto. Para eso hace falta revisión humana.

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
        snippet: >-
          Texto copiado literal de data/patterns/microservices.yaml.
```

Reglas para que el caso sirva:

- `id` único. El harness lo usa como clave en el JSON de resultados.
- Los `snippet` son **texto literal** de `data/patterns/`. Si editas un patrón,
  actualizá el fragmento acá.
- Al menos dos casos con `citations: []` para medir qué hace el modelo cuando el
  recuperador no encontró nada (no debería inventar marcadores `[N]`).
- Al menos un caso donde los patrones expuestos **no** apliquen, para ver si el
  modelo alucina o dice que no aplica.

Para elegir qué medir después, `evals/results/<timestamp>.json` guarda el
markdown completo de cada salida, no solo los scores.

## Archivos

| Archivo | Qué hace |
|---------|----------|
| `cases.yaml` | El corpus. Datos estáticos, sin dependencias externas |
| `runner.py` | Scorer puro + runner de ejecución + métricas de variabilidad |
| `test_runner.py` | Tests offline del scorer (sin red, sin API key) |
| `results/` | Salidas completas por corrida, una por timestamp |

`runner.py` importa el prompt real con
`from app.core.proposal_generator import _build_prompt`. El texto del prompt
nunca se copia al harness: si producción cambia el prompt, el golden set se
entera en la corrida siguiente.

## Checklist antes de sacar conclusiones

- [ ] Corriste `--dry-run` y el corpus es válido
- [ ] Usaste `--repeats 5` o más (con 3 las diferencias se ven, pero las medias
      son ruidosas)
- [ ] Comparaste `--temperature 0` contra `--temperature 1.0` para separar
      serving de sampling
- [ ] Miraste `solapamiento_citas`, no solo `tasa_exacta`
- [ ] Repetiste la corrida en otro horario: si los números cambian mucho entre
      corridas, el servicio tiene variabilidad propia
