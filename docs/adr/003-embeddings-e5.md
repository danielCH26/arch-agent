# ADR-003: Embeddings multilingual-e5-small

**Fecha:** 2026-08-23
**Estado:** Aceptado
**Decisor:** Laura + Daniel
**Issue:** #2

## Contexto

Necesitamos un modelo de embeddings que:

1. Soporte español nativamente (el equipo y usuarios son hispanohablantes)
2. Sea open source y local (privacidad + costo $0)
3. Tenga calidad suficiente para RAG de arquitectura de software
4. Sea razonablemente rápido en CPU (sin GPU dedicada)

## Opciones consideradas

| Modelo | Dim | Multi | Calidad EN | Calidad ES |
|--------|-----|-------|-----------|-----------|
| all-mpnet-base-v2 | 768 | ❌ | 63 | ~45 |
| **multilingual-e5-small** | **384** | ✅ | **58** | **52** |
| multilingual-e5-base | 768 | ✅ | 60 | 56 |
| bge-small-en-v1.5 | 384 | ❌ | ~58 | ~40 |

(Métricas aproximadas del benchmark MTEB)

## Decisión

**Elegido: multilingual-e5-small**

Razones:
1. **+15% recall en español** vs all-mpnet (crítico para nosotros)
2. **Mitad de espacio en DB** (384d vs 768d = 1.5KB vs 3KB por vector)
3. **Más rápido en CPU** (~30% más rápido que mpnet)
4. **Privado y gratis** — los datos no salen del entorno
5. **Tamaño manejable** — 470MB descarga única

## Consecuencias

### Positivas
- Excelente soporte multilingüe (ES/EN/100+ idiomas)
- Bajo costo de almacenamiento vectorial
- Privacidad total

### Negativas
- Calidad en inglés es ~5% menor que all-mpnet (aceptable para nuestro caso)
- Requiere prefijo `"query: "` en queries (a veces se olvida)

## Plan de contingencia

Si en Sprint 4 la calidad no alcanza:
- Migrar a `multilingual-e5-base` (768d, +2% calidad)
- Requiere re-indexar todos los embeddings existentes

## Detalle técnico importante

```python
# IMPORTANTE: el modelo E5 requiere prefijos
query_embedding = embeddings.embed_query("query: ¿patrón para e-commerce?")
# Para documentos, LangChain maneja el prefijo automáticamente
```

## Referencias

- [intfloat/multilingual-e5-small](https://huggingface.co/intfloat/multilingual-e5-small)
- [MTEB Leaderboard](https://huggingface.co/spaces/mteb/leaderboard)
