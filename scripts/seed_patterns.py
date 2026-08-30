#!/usr/bin/env python3
"""
Seed de patrones de arquitectura para la base RAG (architect_patterns).

Issue: Caso de ejemplo (seed)
Responsable: Sofía (Backend / Agente)
Sprint: 1

Carga un conjunto inicial de patrones de arquitectura de software, cada uno
con su embedding (multilingual-e5-small, 384d — ADR-003), para que el
agente pueda consultarlos por similitud semántica durante la fase de
propuesta.

Uso:
    docker compose exec app python scripts/seed_patterns.py

Requiere:
    sentence-transformers (para generar los embeddings)
"""

import json
import sys

from seed_common import connect_db, log

# ---------------------------------------------------------------------------
# Patrones de ejemplo
# ---------------------------------------------------------------------------
# Cada patrón sigue las columnas de architect_patterns. "tradeoffs" incluye
# mínimo 2 ventajas y 2 desventajas, el mismo criterio de aceptación que ya
# usa HU7 (tabla comparativa de trade-offs) en el backlog del equipo.
PATTERNS = [
    {
        "pattern_name": "Arquitectura en capas (Layered)",
        "category": "Monolítica",
        "description": (
            "Organiza el sistema en capas horizontales (presentación, "
            "lógica de negocio, acceso a datos), cada una dependiendo "
            "solo de la capa inmediatamente inferior."
        ),
        "use_cases": (
            "Aplicaciones CRUD de tamaño pequeño a mediano, equipos "
            "pequeños, proyectos con alcance bien definido y bajo "
            "requerimiento de escalar módulos por separado."
        ),
        "tradeoffs": {
            "ventajas": [
                "Curva de aprendizaje baja, fácil de entender para equipos nuevos",
                "Despliegue único, sin complejidad de infraestructura distribuida",
            ],
            "desventajas": [
                "Escala como una sola unidad, no permite escalar módulos por separado",
                "Tiende a acoplarse y volverse difícil de mantener a medida que crece",
            ],
        },
    },
    {
        "pattern_name": "Arquitectura hexagonal (Puertos y Adaptadores)",
        "category": "Monolítica",
        "description": (
            "Aísla la lógica de negocio del núcleo mediante puertos "
            "(interfaces) y adaptadores, de forma que la tecnología externa "
            "(DB, UI, APIs) se pueda cambiar sin tocar el dominio."
        ),
        "use_cases": (
            "Sistemas donde se anticipan cambios de tecnología externa "
            "(DB, proveedor de mensajería) o que requieren alta cobertura "
            "de tests unitarios del dominio."
        ),
        "tradeoffs": {
            "ventajas": [
                "Dominio testeable de forma aislada, sin dependencias externas",
                "Cambiar de tecnología externa (DB, cola, UI) no afecta la lógica de negocio",
            ],
            "desventajas": [
                "Más código repetitivo (boilerplate) que una arquitectura en capas simple",
                "Curva de aprendizaje más alta para equipos sin experiencia previa",
            ],
        },
    },
    {
        "pattern_name": "Monolito modular (Modular Monolith)",
        "category": "Monolítica",
        "description": (
            "Un único despliegue, pero organizado internamente en módulos "
            "con límites explícitos (bounded contexts), como paso "
            "intermedio antes de migrar a microservicios."
        ),
        "use_cases": (
            "Equipos que quieren orden y límites claros entre dominios sin "
            "asumir todavía el costo operativo de microservicios."
        ),
        "tradeoffs": {
            "ventajas": [
                "Mantiene la simplicidad operativa de un solo despliegue",
                "Facilita una futura migración a microservicios si el proyecto crece",
            ],
            "desventajas": [
                "Requiere disciplina del equipo para no romper los límites entre módulos",
                "No resuelve el escalado independiente de módulos, solo lo organiza",
            ],
        },
    },
    {
        "pattern_name": "Microservicios",
        "category": "Distribuida",
        "description": (
            "Divide el sistema en servicios pequeños e independientes, "
            "cada uno con su propia base de datos y ciclo de despliegue, "
            "comunicados por red."
        ),
        "use_cases": (
            "Productos con múltiples equipos trabajando en paralelo, "
            "módulos con necesidades de escalado muy distintas entre sí."
        ),
        "tradeoffs": {
            "ventajas": [
                "Escalado y despliegue independiente por servicio",
                "Equipos pueden trabajar y liberar en paralelo sin bloquearse entre sí",
            ],
            "desventajas": [
                "Alta complejidad operativa: red, observabilidad, consistencia de datos",
                "Requiere más infraestructura y experiencia DevOps desde el día uno",
            ],
        },
    },
    {
        "pattern_name": "Arquitectura orientada a eventos (Event-Driven)",
        "category": "Distribuida",
        "description": (
            "Los componentes se comunican mediante eventos publicados a un "
            "bus o cola, en vez de llamadas directas, favoreciendo el bajo "
            "acoplamiento temporal."
        ),
        "use_cases": (
            "Sistemas con notificaciones en tiempo real, flujos "
            "asíncronos, o integraciones entre módulos que no deben "
            "bloquearse entre sí."
        ),
        "tradeoffs": {
            "ventajas": [
                "Bajo acoplamiento: los productores no conocen a los consumidores",
                "Buen ajuste natural para notificaciones y procesamiento asíncrono",
            ],
            "desventajas": [
                "Depurar el flujo completo de un evento es más difícil (trazabilidad)",
                "Requiere infraestructura de mensajería adicional (cola o bus de eventos)",
            ],
        },
    },
    {
        "pattern_name": "CQRS (Command Query Responsibility Segregation)",
        "category": "Patrón de datos",
        "description": (
            "Separa el modelo de escritura (comandos) del modelo de "
            "lectura (consultas), permitiendo optimizar cada uno de forma "
            "independiente."
        ),
        "use_cases": (
            "Sistemas con patrones de lectura y escritura muy distintos "
            "entre sí, o con necesidad de escalar las lecturas por separado."
        ),
        "tradeoffs": {
            "ventajas": [
                "Permite optimizar y escalar lecturas y escrituras de forma independiente",
                "Modelos de lectura simplificados, adaptados exactamente a cada vista",
            ],
            "desventajas": [
                "Añade complejidad de sincronización entre el modelo de escritura y de lectura",
                "Sobredimensionado para sistemas con carga de lectura/escritura simple",
            ],
        },
    },
    {
        "pattern_name": "Serverless (Function-as-a-Service)",
        "category": "Distribuida",
        "description": (
            "La lógica se despliega como funciones individuales que "
            "ejecuta el proveedor cloud bajo demanda, sin gestionar "
            "servidores directamente."
        ),
        "use_cases": (
            "Cargas de trabajo intermitentes o impredecibles, equipos sin "
            "capacidad de operar infraestructura propia."
        ),
        "tradeoffs": {
            "ventajas": [
                "Sin gestión de servidores; se paga solo por ejecución real",
                "Escala automáticamente ante picos de tráfico sin intervención manual",
            ],
            "desventajas": [
                "Cold starts pueden afectar la latencia en funciones poco usadas",
                "Dependencia fuerte del proveedor cloud (vendor lock-in)",
            ],
        },
    },
    {
        "pattern_name": "API Gateway + Backend for Frontend (BFF)",
        "category": "Distribuida / Integración",
        "description": (
            "Un punto de entrada único (API Gateway) enruta y agrega "
            "llamadas a servicios internos, con una capa BFF adaptada a "
            "las necesidades de cada tipo de cliente (web, móvil)."
        ),
        "use_cases": (
            "Sistemas con múltiples clientes (web, móvil) que consumen "
            "varios servicios backend y necesitan una capa de agregación."
        ),
        "tradeoffs": {
            "ventajas": [
                "Simplifica el cliente: una sola llamada agrega varios servicios internos",
                "Permite adaptar la respuesta a cada tipo de cliente sin duplicar lógica de negocio",
            ],
            "desventajas": [
                "El gateway puede volverse un cuello de botella o un punto único de fallo",
                "Solo tiene sentido si ya existen varios servicios internos que agregar",
            ],
        },
    },
]

_model = None


def get_model():
    """Carga (una sola vez) el modelo de embeddings multilingual-e5-small."""
    global _model
    if _model is None:
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError:
            log(
                "Falta la dependencia 'sentence-transformers'. Instálala con: "
                "pip install sentence-transformers",
                "ERROR",
            )
            sys.exit(1)
        log("Cargando modelo de embeddings (intfloat/multilingual-e5-small)...")
        _model = SentenceTransformer("intfloat/multilingual-e5-small")
        log("Modelo cargado", "OK")
    return _model


def embed_passage(text: str) -> list:
    """Embedding de un texto tipo 'documento' (prefijo e5 'passage: ')."""
    model = get_model()
    vector = model.encode(f"passage: {text}", normalize_embeddings=True)
    return vector.tolist()


def embed_query(text: str) -> list:
    """Embedding de un texto tipo 'consulta' (prefijo e5 'query: ')."""
    model = get_model()
    vector = model.encode(f"query: {text}", normalize_embeddings=True)
    return vector.tolist()


def to_pgvector_literal(vector: list) -> str:
    """Convierte una lista de floats al formato literal que espera PGVector."""
    return "[" + ",".join(f"{v:.8f}" for v in vector) + "]"


def seed_patterns(conn):
    """Inserta los patrones que aún no existan (idempotente por pattern_name)."""
    cur = conn.cursor()
    inserted = 0
    skipped = 0
    for pattern in PATTERNS:
        cur.execute(
            "SELECT 1 FROM architect_patterns WHERE pattern_name = %s",
            (pattern["pattern_name"],),
        )
        if cur.fetchone():
            skipped += 1
            continue

        embedding_text = f"{pattern['description']} {pattern['use_cases']}"
        embedding = to_pgvector_literal(embed_passage(embedding_text))

        cur.execute(
            """
            INSERT INTO architect_patterns
                (pattern_name, category, description, use_cases, tradeoffs, embedding)
            VALUES (%s, %s, %s, %s, %s, %s::vector)
            """,
            (
                pattern["pattern_name"],
                pattern["category"],
                pattern["description"],
                pattern["use_cases"],
                json.dumps(pattern["tradeoffs"]),
                embedding,
            ),
        )
        inserted += 1

    log(f"Patrones insertados: {inserted}, ya existentes (omitidos): {skipped}", "OK")
    return inserted, skipped


def main():
    log("=" * 60)
    log("Seed de patrones de arquitectura (architect_patterns)")
    log("=" * 60)
    conn = connect_db()
    try:
        seed_patterns(conn)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
