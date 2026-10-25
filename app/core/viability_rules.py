"""Reglas de viabilidad compartidas entre los prompts de la propuesta y del ADR.

Antes cada prompt tenía su copia. La propuesta prohibía listar CI/CD,
contenedores o servidor WSGI e inventar SLAs, y limitaba a 6 las tecnologías.
La guía del ADR (sección 7) no tenía ninguna de esas reglas, y por eso
terminaba recomendando Gunicorn, Docker, GitHub Actions, "SLA 99 %",
"2 vCPU/4 GB" o "<$150/mes" que nadie había pedido.

Las reglas comunes viven aquí: si se ajusta una, cambia en los dos prompts.
"""

from __future__ import annotations

PROPORTIONALITY_RULE = (
    "- PROPORCIONALIDAD: dimensiona la solución al proyecto, no al patrón. "
    "Un proyecto sencillo (CRUD, pocos usuarios, MVP, prototipo o trabajo "
    "académico, equipo pequeño o presupuesto bajo) se resuelve con un solo "
    "despliegue, una sola base de datos y servicios gestionados o de capa "
    "gratuita. Cada pieza que agregue costo u operación (broker de "
    "mensajes, API Gateway propio, orquestador tipo Kubernetes, segunda "
    "base de datos, caché distribuida, service mesh, CQRS, event sourcing, "
    "observabilidad centralizada) SOLO se incluye si un requisito "
    "explícito la exige (volumen, disponibilidad, integración). Si no "
    "hay ese requisito, no la incluyas.\n"
)

TECHNOLOGY_LIMIT_RULE = (
    "- Tecnologías: como máximo 6 en un proyecto sencillo (lenguaje, "
    "framework, base de datos y solo lo que un requisito exija). NO listes "
    "como componente ni tecnología CI/CD, backups, servidor ASGI/WSGI, "
    "librería de hash, contenedores ni herramientas de despliegue salvo que "
    "un requisito los pida.\n"
)

FRAMEWORK_LAYERS_RULE = (
    "- No agregues capas que el framework ya trae (por ejemplo "
    "Repository/DAO sobre un ORM, un API Gateway propio dentro de un "
    "monolito, GraphQL además de REST). Para tareas programadas o "
    "recordatorios usa el planificador del framework o un cron; una cola "
    "con broker (Celery + Redis, RabbitMQ...) solo si un requisito exige "
    "reintentos, volumen alto o procesamiento pesado.\n"
)

NO_INVENTED_METRICS_RULE = (
    "- No inventes métricas (latencias, usuarios concurrentes, "
    "disponibilidad, SLAs) que no estén en los requerimientos.\n"
)

UNKNOWN_FIGURES_RULE = (
    "- Con presupuesto, equipo o plazo sin definir, no inventes cifras. "
    "Asume presupuesto y equipo pequeños, declara la incertidumbre como "
    "riesgo o supuesto y elige la opción más conservadora y viable.\n"
)

# El stack se elegía por razones genéricas (barato, rápido, open source) sin
# mirar al equipo, y la composición del equipo se reinterpretaba ("3 front y
# 1 PM" terminaba como "4 desarrolladores backend").
TEAM_FIT_RULE = (
    "- EQUIPO REAL: usa los datos de viabilidad tal como los dijo el usuario. "
    "No reinterpretes la composición del equipo (si dice \"3 front y 1 PM\", "
    "no son 4 desarrolladores backend). Elige tecnologías que el equipo ya "
    "domina (\"Habilidades del equipo\"); si recomiendas una que no domina, "
    "dilo y declara la curva de aprendizaje como riesgo. Justifica cada "
    "tecnología con un dato de ESTE proyecto (equipo, plataforma, fuente de "
    "datos, requisito), no con razones genéricas como \"es barata\" u "
    "\"open source\".\n"
)

# Prueba del observatorio de analítica: la propuesta dio por hecha una
# "región Colombia Central" de Azure (sin evidencia de que exista), afirmó que
# FastAPI respondía "en < 1 s" a un requisito que nadie pidió, citó entre
# comillas un requisito inventado y presentó Logic Apps como "ya dominada" por
# un equipo que solo tenía conocimientos básicos de Azure.
UNVERIFIABLE_FACTS_RULE = (
    "- DATOS QUE NO PUEDES VERIFICAR: no afirmes como hecho regiones o zonas de "
    "un proveedor de nube en un país, la disponibilidad de un servicio en una "
    "región, precios, versiones ni tiempos de respuesta. Si hacen falta, "
    "escríbelos seguidos de `(supuesto)` y deja claro que hay que confirmarlos. "
    "Si el usuario pide verificar uno de esos datos, di explícitamente que no "
    "puedes verificarlo desde aquí y que debe confirmarse en la documentación "
    "oficial del proveedor.\n"
    "- Cada \"Requisito que lo motiva\" debe ser un requisito que está en los "
    "requerimientos; no pongas entre comillas texto que no aparece ahí.\n"
    "- No digas que el equipo domina una tecnología que no está en "
    "\"Habilidades del equipo\".\n"
)

# Bloque común que va, tal cual, en el prompt de la propuesta y en el de la
# guía del ADR.
COMMON_VIABILITY_RULES = (
    TEAM_FIT_RULE
    + PROPORTIONALITY_RULE
    + TECHNOLOGY_LIMIT_RULE
    + FRAMEWORK_LAYERS_RULE
    + NO_INVENTED_METRICS_RULE
    + UNKNOWN_FIGURES_RULE
    + UNVERIFIABLE_FACTS_RULE
)

# Se agrega al prompt de la propuesta solo cuando los requerimientos piden a la
# vez cargas por lotes y datos casi en tiempo real (ver proposal_generator).
REAL_TIME_PATH_RULE = (
    "- LOTES Y TIEMPO REAL: los requerimientos piden datos que se cargan por "
    "lotes y otros que deben estar al día en minutos o en tiempo real. Di "
    "explícitamente qué componente atiende cada vía y con qué frecuencia se "
    "actualiza cada tablero; no digas que no hace falta tiempo real si un "
    "requisito lo pide. Si entre las fuentes hay un patrón que combine ambas "
    "vías (Lambda / Kappa), evalúalo en la tabla de trade-offs.\n"
)

# Marca que la guía del ADR debe poner a todo dato que no viene de la
# propuesta ni de los requerimientos. El lint del ADR la reconoce para no
# avisar dos veces por lo mismo.
ASSUMPTION_MARK = "(supuesto)"

GUIDE_ASSUMPTION_RULES = (
    "- No cambies la arquitectura elegida ni tomes decisiones nuevas: la guía "
    "baja a tierra lo que ya se decidió. Si algo no está decidido, va a 7.8 "
    "Preguntas abiertas, no a la tabla.\n"
    "- Toda cifra (costos, capacidad de servidores, porcentajes, tiempos), "
    "tecnología o componente que NO aparezca en la propuesta aprobada ni en "
    "los requerimientos es un supuesto: escríbelo seguido de "
    f"`{ASSUMPTION_MARK}` y nunca como una decisión tomada.\n"
    "- En 7.2 usa las tecnologías de la propuesta. Si hace falta una que la "
    f"propuesta no nombra, márcala `{ASSUMPTION_MARK}` en la columna "
    "Tecnología y explica en \"Por qué\" qué requisito la motiva.\n"
)
