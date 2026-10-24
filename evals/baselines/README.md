# Baselines del golden set

Este directorio guarda los resúmenes de corridas del golden set
(`python -m evals.runner`) con fecha y parámetros, para que la referencia de
"cuánto dispersa el modelo" sea auditable y no quede solo en la descripción de
un PR. Los `.md` de acá se versionan (`.gitignore` tiene la excepción
`!evals/baselines/*.md`); los JSON completos de `evals/results/` no.

## Convención

Un archivo por corrida, nombrado por fecha y configuración:

```
YYYY-MM-DD_<modelo>_<temp>_<casos>x<repeats>.md
```

Ejemplo: `2026-10-04_gpt-oss-120b_temp0_11x5.md` (el `/` del id del modelo se
omite en el nombre del archivo; el id exacto va adentro).

Contenido mínimo:

- Fecha y hora (UTC) de inicio y fin. La variación por hora es real y afecta
  la comparabilidad.
- Proveedor (`base_url`), id exacto del modelo, temperatura solicitada,
  su origen (`temperature_origen`: `--temperature`, `LLM_TEMPERATURE` o
  `DEFAULT_LLM_TEMPERATURE`) y efectiva, n (casos × repeats).
- Procedencia, copiada de `metadata.procedencia` del JSON: `git_commit` (y
  `git_sucio`, que debe ser `false`), `cases_yaml_sha256`,
  `build_prompt_fuente_sha256` y versiones de paquetes.
- La tabla de métricas que imprime el runner, incluida la línea "pasan siempre
  / fallan siempre".
- El bloque `gate` (la corrida tiene que haber salido con exit 0) y cualquier
  incidencia: rate limits, reintentos, fallos HTTP, salidas vacías con su
  `finish_reason`.

## Estado

**Pendiente de primera medición.** El baseline citado en #99 se midió con un
runner que tenía el bug B1 (firma de `_build_prompt`), con un corpus distinto
y sin metadata de procedencia; la revisión de lau2413 mostró que esos números
no se reproducen y que la magnitud varía ~2× entre corridas (n=30 por columna
no defiende un porcentaje). Queda superado.

La medición cuesta tokens reales: **coordinar antes de correrla**. Con el
default de la app (Groq):

```bash
export GROQ_API_KEY="gsk_..."
python -m evals.runner --dry-run
python -m evals.runner --models openai/gpt-oss-120b --temperature 0.0 --repeats 5
python -m evals.runner --models openai/gpt-oss-120b --temperature 1.0 --repeats 5
```

Cada corrida son 11 casos × 5 repeats = 55 llamadas. Con `--sleep 2.2`
solo las esperas entre llamadas ya suman ~2 minutos; el total (con la
generacion de cada respuesta) es mayor.

Criterio de lau2413 (I5): al menos 2 corridas por temperatura, con 5 repeats o
más, en horarios distintos; guardar todos los resúmenes acá. `temperature=0`
NO da determinismo (Expected Batch Invariance): lo que se documenta es la
reducción de dispersión, no estabilidad byte a byte.
