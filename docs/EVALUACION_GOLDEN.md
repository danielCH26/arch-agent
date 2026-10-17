# Evaluación golden de la propuesta y el ADR

`scripts/eval_pattern_retrieval.py` mide solo el retrieval (top-1/top-3), y sus 24
casos comparten vocabulario con los escenarios del catálogo (ver
[MEJORAS_RETRIEVAL_PATRONES.md](MEJORAS_RETRIEVAL_PATRONES.md)). Esta evaluación
mira lo que recibe el usuario: la tabla de trade-offs y el ADR.

## Casos

`data/golden/*.yaml`: 8 proyectos variados.

| Caso | Tipo | Qué fija |
|---|---|---|
| `crud-biblioteca` | CRUD pequeño | Proyecto académico chico: monolito, ≤ 6 tecnologías |
| `mascotas-perdidas` | geolocalización | **Regresión** del ADR real: Gunicorn, Docker, "SLA 99 %", "2 vCPU/4 GB", sin mapas |
| `clinica-citas` | datos personales | Dominio salud: datos sensibles y recordatorios |
| `tienda-online` | e-commerce | Pagos y fotos del catálogo |
| `analitica-ventas` | datos | Pipeline ETL e integración con el ERP |
| `ml-recomendaciones` | datos / ML | MLOps; una cifra marcada `(supuesto)` es válida |
| `logistica-empresa` | empresa grande | 25 personas: los microservicios están permitidos |
| `reservas-gimnasio` | MVP con reservas | **Caso negativo**: recomienda microservicios con 2 personas y 2 meses |

Cada caso trae el perfil, el resumen y las respuestas de la elicitación, los
candidatos que devolvería el retrieval, una propuesta y una guía grabadas, y el
resultado esperado de cada check.

## Rúbrica (`app/core/adr_rubric.py`)

| Check | Qué revisa |
|---|---|
| `respeta_restricciones` | Con equipo chico y plazo corto, ni el principal ni la recomendación son distribuidos; en un proyecto chico, 7.2 tiene ≤ 6 tecnologías |
| `cifras_con_origen` | La guía no trae SLA, dinero, capacidad ni latencias que no estén en los requerimientos o la propuesta (salvo `(supuesto)`) |
| `coherencia` | La recomendación es el patrón principal; los componentes de 7.1 salen de la propuesta o del diagrama; 7.2 no agrega tecnologías nuevas |
| `alternativas_diversas` | Las filas de la tabla son de al menos dos familias (`family` en `data/patterns/*.yaml`) |
| `preocupaciones_dominio` | Se detectan las preocupaciones esperadas (mapas, archivos, pagos...) y el ADR las trata |

## Cómo se corre

- **CI**: `tests/eval/test_golden_rubric.py` corre con el resto de pytest en cada
  PR y compara la rúbrica con lo esperado de cada caso. El job también imprime la
  tabla (`python scripts/eval_adr_golden.py`).
- **Contra un LLM real**, cuando cambies un prompt:

  ```bash
  export EVAL_LLM_API_KEY=...            # Groq u otro proveedor compatible con OpenAI
  python scripts/eval_adr_golden.py --live --min-score 0.8
  python scripts/eval_adr_golden.py --live --case mascotas-perdidas
  ```

  Variables opcionales: `EVAL_LLM_MODEL` (default `openai/gpt-oss-120b`),
  `EVAL_LLM_BASE_URL` y `EVAL_WAIT_S` (pausa entre casos, por el límite de
  tokens por minuto).

Para agregar un caso, copia uno de `data/golden/`, cambia el proyecto y graba la
salida de una corrida `--live` en `recorded`.
