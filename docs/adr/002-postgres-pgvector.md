# ADR-002: PostgreSQL + PGVector como base de datos única

**Fecha:** 2026-08-23
**Estado:** Aceptado
**Decisor:** Daniel + Laura
**Issue:** #2

## Contexto

El sistema necesita dos tipos de almacenamiento:

1. **Datos relacionales:** users, projects, sessions, logs, approvals
2. **Vectores:** embeddings de patrones y documentos del usuario (RAG)

Las opciones eran:
- Una sola DB con extensión vectorial
- Dos DBs separadas (ej: Postgres + Chroma)
- Soluciones especializadas (Pinecone, Qdrant)

## Opciones consideradas

| Opción | Pros | Contras |
|--------|------|---------|
| **PostgreSQL + PGVector** | Una sola DB, joins SQL, production-ready | Menos especializado que vector DB puro |
| Postgres + Chroma | Cada uno hace lo suyo bien | 2 servicios, complejidad operacional |
| Postgres + Qdrant | Qdrant es muy rápido | 2 servicios, otro lenguaje |
| Solo SQLite | Simple, sin servidor | Limitaciones de concurrencia |
| Pinecone (cloud) | Excelente vectorial | Costo, datos fuera del entorno |

## Decisión

**Elegido: PostgreSQL 16 + extensión PGVector**

Razones:
1. **Un solo servicio Docker** — menos complejidad operacional
2. **Joins SQL** entre metadata de patrones y embeddings
3. **Production-ready** desde día 1
4. **Imagen oficial** `pgvector/pgvector:pg16` ya incluye la extensión
5. **LangChain tiene `langchain-postgres`** con clase `PGVector` oficial

## Consecuencias

### Positivas
- Menos servicios que mantener (1 vs 2)
- Transacciones ACID para datos relacionales
- Backups simples (un solo `pg_dump`)

### Negativas
- Búsqueda vectorial es buena pero no tan rápida como Qdrant
- Para millones de vectores podría requerir optimización

## Alternativa futura

Si el volumen crece significativamente (>100k patrones), migrar a Qdrant.
SQLAlchemy abstrae la DB: solo cambiar el connection string y la clase del vector store.

## Referencias

- [PGVector](https://github.com/pgvector/pgvector)
- [langchain-postgres](https://python.langchain.com/docs/integrations/vectorstores/pgvector)
- Schema completo: `docs/database/SCHEMA.md`
