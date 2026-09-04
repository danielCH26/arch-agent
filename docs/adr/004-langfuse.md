# ADR-004: Langfuse self-hosted para observabilidad

**Fecha:** 2026-08-23
**Estado:** Aceptado
**Decisor:** Daniel + Santiago
**Issue:** #2

## Contexto

Necesitamos trazabilidad completa de las llamadas al LLM para:

1. Cumplir OKR 4 - KR1: "100% de las ejecuciones registradas en trazas"
2. Medir latencia (constraint < 3 min)
3. Auditar qué consultas hace el agente
4. Visualizar el flujo en una UI para demos

## Opciones consideradas

| Opción | Pros | Contras |
|--------|------|---------|
| **Langfuse self-hosted** | UI rica, open source, integración nativa LangChain | 5 servicios Docker extra |
| LangSmith (cloud) | Simple, oficial LangChain | Datos fuera del entorno, pago |
| Custom (tabla propia) | $0, simple | Sin UI, solo SQL |
| OpenLLMetry + Jaeger | Estándar OpenTelemetry | Complejo, sin UI específica para LLM |

## Decisión

**Elegido: Langfuse self-hosted**

Razones:
1. **UI de tracing incluida** — fundamental para demo final
2. **Integración nativa** vía `CallbackHandler` de LangChain
3. **Open source** — sin dependencia de SaaS
4. **Mejor demo para el cierre académico**
5. **Cumple OKR de Santiago** (Docker / Aux. Agente)

## Stack de Langfuse (5 servicios)

```
┌─────────────────────────────────────────┐
│  Langfuse self-hosted                    │
│  ┌──────────┐  ┌──────────┐            │
│  │ Langfuse │  │ Langfuse │            │
│  │   Web    │  │    DB    │            │
│  └──────────┘  └──────────┘            │
│  ┌──────────┐  ┌──────────┐  ┌──────┐ │
│  │Clickhouse│  │  Minio   │  │ Redis│ │
│  │(analytics)│ │ (storage)│  │(cache)│ │
│  └──────────┘  └──────────┘  └──────┘ │
└─────────────────────────────────────────┘
```

## Consecuencias

### Positivas
- UI profesional para el cierre del proyecto
- Trazabilidad completa (cumple OKR 4 - KR1)
- Open source y self-hosted

### Negativas
- **5 servicios Docker adicionales** (total 8 en el stack)
- ClickHouse consume ~500MB-1GB de RAM
- Requiere mantenimiento (updates, backups)

## Tabla fallback

**Mantenemos `interaction_logs` en Postgres** además de Langfuse. Razones:
- Queries de negocio SQL son más simples que navegar UI de Langfuse
- Funciona como **fallback** si Langfuse se cae
- **Defense in depth**: dos sistemas independientes

## Referencias

- [Langfuse](https://langfuse.com)
- [LangChain CallbackHandler](https://langfuse.com/docs/integrations/langchain)
- Setup detallado en `STACK_TECNOLOGICO.md` sección 12
