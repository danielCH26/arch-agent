# ADR-001: LangChain como framework del agente

**Fecha:** 2026-08-23
**Estado:** Aceptado
**Decisor:** Daniel (Tech Lead)
**Issue:** #2

## Contexto

Necesitamos un framework para construir el agente de IA que:

1. Soporte múltiples proveedores de LLM (configurable por usuario)
2. Tenga integración nativa con RAG y vector stores
3. Permita agregar tools (MCPs) de forma sencilla
4. Tenga documentación sólida y comunidad activa
5. Sea open source

## Opciones consideradas

| Opción | Pros | Contras |
|--------|------|---------|
| **LangChain** | Multi-provider nativo, RAG integrado, comunidad grande, MCPs | Curva de aprendizaje media |
| LlamaIndex | Especializado en RAG | Menos flexible para herramientas |
| CrewAI | Multi-agente simple | Menos maduro, menos documentación |
| Custom (sin framework) | Máximo control | Reimplementar todo, riesgo alto |

## Decisión

**Elegido: LangChain**

Razones principales:
- `init_chat_model()` soporta cualquier API OpenAI-compatible (Ollama, vLLM, OpenAI, etc.)
- Clase `PGVector` oficial para nuestro vector store
- `MultiServerMCPClient` para conectar a nuestros 6 MCPs
- Documentación completa en español e inglés

## Consecuencias

### Positivas
- Rapidez de desarrollo
- Ecosistema de integraciones
- Facilidad para cambiar de LLM provider

### Negativas
- Curva de aprendizaje para el equipo junior
- LangChain cambia rápido (versiones breaking)
- Dependencia externa

## Referencias

- [LangChain Docs](https://python.langchain.com)
- Issue #2: [F02] Arquitectura técnica
