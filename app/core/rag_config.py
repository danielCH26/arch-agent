"""
Configuración compartida del pipeline RAG.

Vive en ``app/core/`` -- y no en ``app/api/chat.py`` -- para que las tres capas
que filtran por relevancia (el chat, la generación de propuestas y el router de
proposals) importen la MISMA constante sin caer en un import circular. ADR-009
dejó el módulo como refactor pendiente; este es ese refactor.
"""

# Umbral MÍNIMO de similitud para considerar un chunk/patrón "relevante".
# Sin esto, ``similarity_search()`` siempre devuelve los top-k más cercanos
# aunque ninguno tenga relación real con la query.
#
# Es un ÚNICO umbral global (no diferenciado por tipo) -- se intentó
# diferenciar por source_type (patrones vs. documentos) pero la evidencia real
# terminó contradiciéndolo: un falso positivo de un documento (PDF de
# matemáticas, en una pregunta de microservicios) salió a 83%, por ENCIMA de un
# verdadero positivo de otro documento real (PDF de grafos/MapReduce, en su
# propia pregunta, a 80-81%). Con este modelo de embeddings
# (multilingual-e5-small), la similitud coseno sola no separa limpiamente
# relevante/irrelevante en la banda 80-88%; no existe un número (global o por
# tipo) que acierte siempre en esa zona gris.
#
# 0.85 es un punto intermedio elegido con la evidencia acumulada:
#   Verdaderos positivos medidos: 88% (patrón), 89-92% (documento).
#   Falsos positivos medidos:     75-78%, 81-83% (ambos tipos).
# Es una heurística "best effort", no una garantía -- puede ocasionalmente dejar
# pasar ruido cerca del límite, o descartar un match débil pero legítimo. Si se
# necesita precisión real en esa zona gris, la solución correcta es un paso de
# re-ranking (ej. que el LLM juzgue relevancia real de cada candidato, o un
# cross-encoder), no seguir ajustando este número. Ver
# docs/QA_criterios_aceptacion_RAG.md.
#
# AVISO: este es un CONTRATO DE NEGOCIO, no un número de tuning. Bajarlo cambia
# qué citas llegan al modelo en TODOS los flujos a la vez (chat, propuestas y
# regeneraciones). Si hay que moverlo, se mueve acá y en un solo lugar.
RAG_MIN_SIMILARITY: float = 0.85
