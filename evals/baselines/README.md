# Baselines del golden set

Este directorio guarda los resúmenes de corridas del golden set
(`python -m evals.runner`) con fecha y parámetros, para que la
referencia de "cuánto dispersa el modelo" sea auditable y no quede
solo en la descripción de un PR.

## Convención

Un archivo por corrida, nombrado por fecha y configuración:

```
YYYY-MM-DD_<modelo>_<temp>_<casos>x<repeats>.md
```

Ejemplo: `2026-10-04_gpt-oss-120b_temp0_10x3.md`.

Contenido mínimo: fecha, modelo, proveedor, temperatura, n (casos ×
repeats), la tabla de métricas que imprime el runner (`struct_ok`,
`exacta`, `acuerdo`, `citas`, `desv_lg`) y cualquier incidencia
(rate limits, fallos HTTP, hora del día — la variación por hora es
real y relevante para la comparabilidad).

## Estado

**Pendiente de primera medición en este branch.** El baseline citado
en #99 se midió con un runner que tenía el bug B1 (firma de
`_build_prompt`); la revisión de lau2413 demostró que esos números no
se reproducen y que la magnitud varía entre corridas (n=30 por columna
no defiende un porcentaje). Con el runner arreglado (este PR), la
primera corrida hay que rehacerla:

```
export GROQ_API_KEY=...   # cuesta tokens reales: coordinar antes
python -m evals.runner --models openai/gpt-oss-120b --temperature 0.0 --repeats 5
python -m evals.runner --models openai/gpt-oss-120b --temperature 1.0 --repeats 5
```

Criterio de lau2413 (I5): al menos 2 corridas por temperatura y 5
repeats o más; guardar ambos resúmenes acá. `temperature=0` NO da
determinismo (Expected Batch Invariance): lo que se documenta es la
reducción de dispersión, no byte-a-byte.
