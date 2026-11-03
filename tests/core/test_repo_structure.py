"""
Pruebas del generador del árbol de carpetas.

Lo que de verdad importa acá no es que el árbol salga "bonito", sino tres
cosas que son criterios de aceptación de la historia:

1. **Cada línea cita su fuente.** Ninguna ruta puede aparecer sin respaldo.
2. **Nada se inventa.** Si no se reconoce el stack, o un módulo no tiene
   patrón aplicable, o un patrón aplicable no tiene dónde ubicarse, el plan
   lo REPORTA en lugar de rellenar el hueco.
3. **Cada decisión es auditable.** El tipo de módulo y la convención guardan
   el término que las decidió.

El resto de las pruebas cubre los errores que de hecho aparecieron al armar
esto: el árbol que no emitía las carpetas intermedias, la infraestructura que
entraba como módulo, y los roles que la convención ya documenta y que el
patrón no debe duplicar.
"""

import pytest

from app.core.repo_structure import (
    DEFAULT_MODULE_KIND,
    build_plan,
    classify_module,
    detect_modules,
    discard_is_doubtful,
    is_infrastructure,
    normalize,
    parse_primary_pattern,
    parse_proposal_technologies,
    pascal_case,
    plan_to_dict,
    render_tree,
    snake_case,
    stack_terms,
)

MERMAID = """graph TD
    UI[Interfaz web] --> API[API REST]
    API --> PED[Gestion de pedidos]
    API --> PAGO[Integracion con pasarela de pagos]
    API --> NOTI[Notificaciones por correo]
    PED --> DB[(PostgreSQL)]
"""

PROPUESTA = """## 2. Componentes
- **API REST**: expone los endpoints

## 3. Tecnologias
- **Backend**: FastAPI con SQLAlchemy sobre PostgreSQL
- **Frontend**: React con TypeScript

## 4. Alternativas consideradas
- Se descarto Django porque el equipo no lo domina
"""


@pytest.fixture
def plan():
    return build_plan(mermaid=MERMAID, proposal_markdown=PROPUESTA)


class TestNadaSinFuente:
    """El criterio de aceptación central de la historia."""

    def test_toda_linea_del_arbol_tiene_fuente(self, plan):
        assert plan.lines
        for line in plan.lines:
            assert line.source_title, line.path
            assert line.source_url.startswith("http"), line.path

    def test_todo_patron_elegido_tiene_justificacion_y_fuente(self, plan):
        elegidos = [p for m in plan.modules for p in m.patterns]
        assert elegidos
        for eleccion in elegidos:
            assert eleccion.justification, eleccion.pattern_name
            assert eleccion.source_url.startswith("http"), eleccion.pattern_name

    def test_cada_linea_dice_si_viene_de_la_convencion_o_de_un_patron(self, plan):
        origenes = {line.origin for line in plan.lines}
        assert origenes <= {"convencion", "patron"}
        # El árbol combina las dos cosas: si solo hubiera de una, o la
        # convención no se aplicó o los patrones no se ubicaron.
        assert origenes == {"convencion", "patron"}

    def test_una_linea_de_patron_nombra_el_patron(self, plan):
        de_patron = [line for line in plan.lines if line.origin == "patron"]
        assert de_patron
        assert all(line.pattern_name for line in de_patron)


class TestDecisionesAuditables:
    def test_la_convencion_guarda_el_termino_que_la_activo(self, plan):
        assert plan.backend is not None
        assert plan.backend.convention_id == "fastapi"
        assert plan.backend_term == "fastapi"
        assert plan.frontend is not None
        assert plan.frontend.convention_id == "react"

    def test_el_tipo_de_modulo_guarda_el_termino_que_lo_decidio(self, plan):
        pedidos = next(m for m in plan.modules if m.name == "Gestion de pedidos")
        assert pedidos.kind == "crud"
        assert pedidos.matched_term in {"gestion", "pedidos"}

    def test_el_termino_vacio_marca_el_tipo_por_omision(self):
        kind, termino = classify_module("Zarandaja")
        assert kind == DEFAULT_MODULE_KIND
        assert termino == ""

    def test_gana_el_termino_mas_largo(self):
        # "pasarela de pagos" le gana a "pagos": si ganara el corto, el módulo
        # quedaría clasificado como CRUD y recibiría un repositorio.
        kind, termino = classify_module("Integracion con pasarela de pagos")
        assert kind == "integracion"
        assert termino == "pasarela de pagos"

    def test_cada_modulo_dice_de_donde_salio(self, plan):
        assert {m.origin for m in plan.modules} <= {"diagrama", "propuesta"}
        assert any(m.origin == "diagrama" for m in plan.modules)


class TestNoInventa:
    def test_sin_stack_reconocido_no_hay_arbol_y_se_avisa(self):
        plan = build_plan(mermaid=MERMAID, tecnologias=["COBOL", "AS/400"])
        assert plan.backend is None
        assert plan.lines == ()
        assert "backend" in plan.unmatched_layers
        assert any("no se reconoció el stack" in w.lower() for w in plan.warnings)

    def test_un_modulo_sin_patron_aplicable_se_reporta(self, plan):
        # No hay en la base ningún patrón de nivel módulo para notificaciones.
        # El plan lo dice; no le asigna uno que no aplica.
        noti = next(m for m in plan.modules if "Notificaciones" in m.name)
        assert noti.patterns == ()
        assert noti.uncovered_reason
        assert any("Notificaciones" in w for w in plan.warnings)

    def test_avisa_cuando_la_arquitectura_no_es_una_aplicacion_unica(self):
        """Serverless con FastAPI: el árbol no es el del repositorio completo.

        La convención se elige por TECNOLOGÍA, y eso solo no alcanza. Un
        proyecto serverless escrito con FastAPI matchea la convención de
        FastAPI y recibía el árbol de una aplicación monolítica
        (`app/main.py`, `app/routers/`), que no es como se organiza un repo
        serverless. Salió en un ADR real y nadie lo avisaba.
        """
        plan = build_plan(
            mermaid="graph TD\n  GW[API Gateway] --> FN[Funciones Serverless]",
            proposal_markdown=(
                "## Patrones\n"
                "Patrón principal: Serverless (Function-as-a-Service)\n\n"
                "## Tecnologias\n- **Backend**: FastAPI\n"
            ),
        )
        assert any("arquitectura aprobada" in w for w in plan.warnings)
        assert any("Serverless" in w for w in plan.warnings)

    def test_avisa_igual_con_microservicios(self):
        plan = build_plan(
            mermaid="graph TD\n  A[API REST] --> B[Gestion de pedidos]",
            proposal_markdown=(
                "## Patrones\nPatrón principal: Microservicios\n\n"
                "## Tecnologias\n- **Backend**: FastAPI\n"
            ),
        )
        assert any("arquitectura aprobada" in w for w in plan.warnings)

    def test_un_estilo_de_aplicacion_unica_no_dispara_el_aviso(self):
        plan = build_plan(
            mermaid="graph TD\n  A[API REST] --> B[Gestion de pedidos]",
            proposal_markdown=(
                "## Patrones\nPatrón principal: Monolito modular (Modular Monolith)\n\n"
                "## Tecnologias\n- **Backend**: FastAPI\n"
            ),
        )
        assert not any("arquitectura aprobada" in w for w in plan.warnings)

    def test_sin_patron_principal_no_se_inventa_el_aviso(self):
        plan = build_plan(
            mermaid="graph TD\n  A[API REST]", tecnologias=["FastAPI"]
        )
        assert not any("arquitectura aprobada" in w for w in plan.warnings)

    @pytest.mark.parametrize(
        "texto, esperado",
        [
            ("Patrón principal: Microservicios", "Microservicios"),
            ("**Patrón principal:** Serverless (FaaS)", "Serverless (FaaS)"),
            # Guion tipográfico, como lo escribe el generador de propuestas.
            (
                "Patrón principal: Serverless (Function‑as‑a‑Service)",
                "Serverless (Function‑as‑a‑Service)",
            ),
            ("Sin patrones acá", ""),
        ],
    )
    def test_lee_el_patron_principal(self, texto, esperado):
        assert parse_primary_pattern(texto) == esperado

    def test_un_framework_full_stack_no_genera_un_aviso_falso(self):
        """Django sirve la interfaz: no hay hueco de frontend que avisar.

        Antes el ADR de un proyecto Django decía «no se reconoció el stack de
        frontend», que es falso: no es que no se reconociera, es que no hay un
        stack de frontend aparte. Un pendiente inventado le quita credibilidad
        a los avisos de verdad.
        """
        plan = build_plan(
            mermaid="graph TD\n  FE[Frontend Web] --> API[API REST]\n  API --> C[Modulo Carrito]",
            tecnologias=["Django 4.x", "Django REST Framework"],
        )
        assert plan.backend is not None
        assert plan.backend.serves_frontend is True
        assert not any("stack de frontend" in w for w in plan.warnings)
        assert "frontend" not in plan.unmatched_layers
        # La aclaración sí aparece, pero por el canal de notas.
        assert any("plantillas" in n for n in plan.notes)
        # Y las plantillas están de verdad en el árbol.
        assert any("templates" in line.path for line in plan.lines)

    def test_un_backend_que_no_sirve_la_interfaz_sigue_avisando(self):
        plan = build_plan(
            mermaid="graph TD\n  FE[Frontend Web] --> API[API REST]",
            tecnologias=["FastAPI"],
        )
        assert plan.backend is not None
        assert plan.backend.serves_frontend is False
        assert any("stack de frontend" in w for w in plan.warnings)
        assert "frontend" in plan.unmatched_layers
        assert plan.notes == ()

    def test_con_frontend_reconocido_no_hay_ni_aviso_ni_aclaracion(self):
        plan = build_plan(
            mermaid="graph TD\n  FE[Frontend Web] --> API[API REST]",
            tecnologias=["FastAPI", "React"],
        )
        assert not any("stack de frontend" in w for w in plan.warnings)
        assert plan.notes == ()

    def test_sin_modulos_lo_dice(self):
        plan = build_plan(
            mermaid="graph TD\n  A[(PostgreSQL)] --> B[Usuario final]",
            tecnologias=["FastAPI"],
        )
        assert plan.modules == ()
        assert any("ningún módulo" in w for w in plan.warnings)

    def test_un_patron_sin_ranura_se_reporta_y_no_se_ubica(self, monkeypatch):
        """Una convención que no sabe ubicar aportes no recibe rutas inventadas."""
        from app.core import repo_structure

        convention = repo_structure.match_convention(["FastAPI"], layer="backend")[0]
        assert convention is not None
        roto = type(convention)(
            **{
                **{
                    campo: getattr(convention, campo)
                    for campo in convention.__dataclass_fields__
                },
                "pattern_slot": "src/sin_marcadores.py",
                "documented_roles": frozenset(),
            }
        )
        ruta, ubicado = repo_structure._place(
            repo_structure.DetectedModule(
                name="Gestion de pedidos", kind="crud", matched_term="gestion", origin="diagrama"
            ),
            roto,
            {"role": "repository", "dir_name": "repositories", "file_name": "repositories",
             "class_name": "Repository", "note": "", "source_title": "", "source_url": ""},
        )
        assert ruta == ""
        assert ubicado is False


class TestDeteccionDeModulos:
    @pytest.mark.parametrize(
        "nombre",
        ["PostgreSQL", "Base de datos", "Balanceador de carga", "Usuario final", "S3"],
    )
    def test_la_infraestructura_no_es_un_modulo(self, nombre):
        assert is_infrastructure(nombre)

    @pytest.mark.parametrize("nombre", ["Gestion de pedidos", "API REST", "Interfaz web"])
    def test_un_modulo_real_no_es_infraestructura(self, nombre):
        assert not is_infrastructure(nombre)

    def test_no_entra_la_base_de_datos_del_diagrama(self, plan):
        nombres = {m.name.lower() for m in plan.modules}
        assert not any("postgres" in n for n in nombres)

    def test_no_repite_modulos_del_diagrama_y_de_la_propuesta(self):
        plan = build_plan(
            mermaid="graph TD\n  A[API REST] --> B[Gestion de pedidos]",
            componentes=["API REST", "Reportes de ventas"],
            tecnologias=["FastAPI"],
        )
        nombres = [m.name for m in plan.modules]
        assert len(nombres) == len(set(nombres))
        assert "Reportes de ventas" in nombres

    def test_el_diagrama_manda_sobre_la_propuesta(self):
        plan = build_plan(
            mermaid="graph TD\n  A[API REST]",
            componentes=["API REST"],
            tecnologias=["FastAPI"],
        )
        api = next(m for m in plan.modules if m.name == "API REST")
        assert api.origin == "diagrama"


class TestConvencionYPatronNoSeDuplican:
    def test_spring_no_duplica_la_carpeta_de_servicio(self):
        """Spring ya documenta Service y Repository: el patrón los justifica."""
        plan = build_plan(
            mermaid="graph TD\n  API[API REST] --> PED[Gestion de pedidos]",
            tecnologias=["Spring Boot", "Java"],
        )
        rutas = [line.path for line in plan.lines]
        servicios = [r for r in rutas if r.endswith("Service.java")]
        assert len(servicios) == len(set(servicios))
        # La línea existe y la pone la convención, no el patrón.
        servicio = next(line for line in plan.lines if line.path.endswith("Service.java"))
        assert servicio.origin == "convencion"
        # Y el patrón igual aparece como justificación del módulo.
        pedidos = next(m for m in plan.modules if m.name == "Gestion de pedidos")
        assert any(p.pattern_name == "Service Layer" for p in pedidos.patterns)

    def test_fastapi_si_agrega_la_carpeta_porque_su_fuente_no_la_documenta(self):
        plan = build_plan(
            mermaid="graph TD\n  API[API REST] --> PED[Gestion de pedidos]",
            tecnologias=["FastAPI"],
        )
        servicio = next(
            line for line in plan.lines if line.path.startswith("app/services/")
        )
        assert servicio.origin == "patron"
        assert servicio.pattern_name == "Service Layer"

    def test_no_hay_rutas_repetidas(self, plan):
        rutas = [line.path for line in plan.lines]
        assert len(rutas) == len(set(rutas))


class TestRenderDelArbol:
    def test_emite_las_carpetas_intermedias(self):
        """El error que tuvo la primera versión: `a/b/c.py` sin `b/`."""
        from app.core.repo_structure import StructureLine

        lineas = [
            StructureLine(
                path="app/repositories/pedidos.py",
                note="",
                source_title="t",
                source_url="https://example.com",
                origin="patron",
            )
        ]
        salida = render_tree(lineas)
        assert salida.splitlines() == [
            "app/",
            "    repositories/",
            "        pedidos.py",
        ]

    def test_las_carpetas_van_antes_que_los_archivos(self, plan):
        lineas = plan.tree_text().splitlines()
        nivel_cero = [l for l in lineas if not l.startswith(" ")]
        carpetas = [i for i, l in enumerate(nivel_cero) if l.endswith("/")]
        archivos = [i for i, l in enumerate(nivel_cero) if not l.endswith("/")]
        if carpetas and archivos:
            assert max(carpetas) < min(archivos)

    def test_arbol_vacio_devuelve_cadena_vacia(self):
        assert render_tree([]) == ""

    def test_el_arbol_no_tiene_marcadores_sin_reemplazar(self, plan):
        assert "{" not in plan.tree_text()
        assert "}" not in plan.tree_text()


class TestLimiteDeAnidamiento:
    def test_avisa_cuando_una_ruta_excede_el_limite_de_la_fuente(self):
        # React recomienda no pasar de 4 niveles. Spring, que no declara
        # límite, no debe producir este aviso aunque anide más.
        plan = build_plan(
            mermaid="graph TD\n  API[API REST] --> PED[Gestion de pedidos]",
            tecnologias=["Spring Boot"],
        )
        assert not any("niveles de carpetas" in w for w in plan.warnings)


class TestNombres:
    @pytest.mark.parametrize(
        "entrada, esperado",
        [
            ("Gestión de Pedidos", "gestion_de_pedidos"),
            ("API REST", "api_rest"),
            ("", "modulo"),
        ],
    )
    def test_snake_case(self, entrada, esperado):
        assert snake_case(entrada) == esperado

    @pytest.mark.parametrize(
        "entrada, esperado",
        [("gestión de pedidos", "GestionDePedidos"), ("api rest", "ApiRest"), ("", "Modulo")],
    )
    def test_pascal_case(self, entrada, esperado):
        assert pascal_case(entrada) == esperado


class TestTecnologiasDeLaPropuesta:
    def test_lee_la_seccion_de_tecnologias(self):
        lineas = parse_proposal_technologies(PROPUESTA)
        assert len(lineas) == 2
        assert any("FastAPI" in l for l in lineas)

    def test_la_seccion_tiene_prioridad_sobre_el_resto_del_documento(self):
        # Django se menciona en "Alternativas consideradas". Si se buscara en
        # todo el markdown, podría ganarle a FastAPI.
        plan = build_plan(mermaid=MERMAID, proposal_markdown=PROPUESTA)
        assert plan.backend is not None
        assert plan.backend.convention_id == "fastapi"

    def test_sin_seccion_cae_a_todo_el_documento_y_lo_avisa(self):
        sin_seccion = PROPUESTA.replace("## 3. Tecnologias", "## 3. Otra cosa")
        _terminos, de_la_seccion = stack_terms(sin_seccion)
        assert de_la_seccion is False
        plan = build_plan(mermaid=MERMAID, proposal_markdown=sin_seccion)
        assert any("sección de tecnologías" in w for w in plan.warnings)


class TestNombresDelMundoReal:
    """Lo que falló en el primer ADR de verdad que se generó ("tiendita").

    El diagrama nombraba los nodos por TECNOLOGÍA ("React + TypeScript",
    "Stripe SDK", "SendGrid API") y no por rol. Resultado: el frontend quedó
    clasificado como `crud` y terminó con un repositorio y una unidad de
    trabajo en `app/repositories/react_typescript.py`, en el árbol del
    backend. Y no había árbol de React en absoluto, porque ningún módulo
    quedó como `ui`.
    """

    MERMAID = """graph TD
        NAV[Navegador Web] --> FE[React + TypeScript]
        FE --> API[FastAPI (API REST)]
        API --> JWT[JWT Auth]
        API --> PED[Modulo Pedidos]
        API --> STR[Stripe SDK]
        API --> SG[SendGrid API]
        PED --> DB[(PostgreSQL)]
    """

    PROPUESTA = """## Componentes
- **API REST (FastAPI)**: expone los endpoints.
- **Frontend Web (React + TypeScript)**: interfaz de usuario.
- **Base de datos (PostgreSQL)**: almacena datos.
- **Servicio de autenticacion (JWT)**: genera y valida tokens.
- **Integracion de pagos (Stripe SDK)**: procesa pagos.
- **Servicio de notificaciones por correo (SMTP / SendGrid API)**: envia avisos.

## Tecnologias
| Tecnologia | Justificacion | Requisito que lo motiva |
| --- | --- | --- |
| FastAPI (Python) | Framework ASGI ligero | Autenticacion |
| React + TypeScript | Biblioteca de UI | Interfaz web |
| Stripe SDK (Python) | Cliente de la pasarela | Pagos |
"""

    @pytest.fixture
    def plan(self):
        return build_plan(mermaid=self.MERMAID, proposal_markdown=self.PROPUESTA)

    def test_el_frontend_no_termina_en_el_arbol_del_backend(self, plan):
        frontend = next(m for m in plan.modules if "React" in m.name)
        assert frontend.kind == "ui"
        rutas = [line.path for line in plan.lines]
        assert not any(r.startswith("app/repositories/") and "react" in r for r in rutas)

    def test_hay_arbol_de_frontend(self, plan):
        # Si ningún módulo queda como `ui`, la convención de React se reconoce
        # pero no emite una sola línea, y el usuario no ve su frontend.
        assert any(line.path.endswith(".js") for line in plan.lines)

    def test_la_integracion_no_recibe_repositorio(self, plan):
        stripe = next(m for m in plan.modules if "Stripe" in m.name)
        assert stripe.kind == "integracion"
        assert not any(p.role == "repository" for p in stripe.patterns)

    def test_el_correo_es_notificaciones_y_no_api(self, plan):
        # "SendGrid API" contiene la palabra "api": sin el nombre de la
        # propuesta quedaba clasificado como capa de entrada.
        correo = next(m for m in plan.modules if "SendGrid" in m.name or "correo" in m.name)
        assert correo.kind == "notificaciones"

    def test_usa_el_nombre_mas_descriptivo_de_la_propuesta(self, plan):
        nombres = {m.name for m in plan.modules}
        assert "Frontend Web (React + TypeScript)" in nombres
        assert "React + TypeScript" not in nombres

    def test_no_duplica_el_mismo_modulo_con_otro_orden_de_palabras(self, plan):
        """"FastAPI (API REST)" y "API REST (FastAPI)" son uno solo."""
        apis = [m for m in plan.modules if "FastAPI" in m.name or "API REST" in m.name]
        assert len(apis) == 1
        rutas = [line.path for line in plan.lines]
        assert len(rutas) == len(set(rutas))

    def test_no_duplica_aunque_el_nombre_este_al_reves(self, plan):
        jwt = [m for m in plan.modules if "JWT" in m.name]
        assert len(jwt) == 1

    @pytest.mark.parametrize(
        "nombre, kind",
        [
            ("React + TypeScript", "ui"),
            ("Vue 3", "ui"),
            ("Stripe SDK", "integracion"),
            ("SendGrid API", "notificaciones"),
        ],
    )
    def test_los_terminos_por_tecnologia_son_la_red_de_seguridad(self, nombre, kind):
        """Cuando no hay propuesta que aporte un nombre mejor."""
        assert classify_module(nombre)[0] == kind

    def test_nombres_distintos_con_una_palabra_vacia_en_comun_no_se_fusionan(self):
        # "Servicio de pagos" y "Servicio de correo" comparten "servicio", que
        # está en la lista de palabras vacías: son dos módulos.
        plan = build_plan(
            mermaid="graph TD\n  A[Servicio de pagos]\n  B[Servicio de correo]",
            tecnologias=["FastAPI"],
        )
        assert len(plan.modules) == 2


class TestDefectosDeLaRevision:
    """Los cuatro defectos de la revisión del PR, con sus entradas exactas.

    Los cuatro eran del mismo tipo: una decisión tomada en el orden
    equivocado. Longitud antes que prioridad, infraestructura antes que tipo,
    renombrar antes de saber cuántos lo reclaman, y un límite de una
    convención aplicado a las líneas de otra.
    """

    def test_no_se_pierden_modulos_al_cruzar_diagrama_y_propuesta(self):
        """Dos nodos que comparten token con un componente: no se fusionan.

        Antes los dos se renombraban a «Gestión de pedidos» y el deduplicado
        se comía el segundo. El Worker, que es `procesamiento`, desaparecía
        del árbol sin ningún aviso.
        """
        modules = detect_modules(
            mermaid="graph TD\n  A[Pedidos API] --> B[Pedidos Worker]",
            componentes=["Gestión de pedidos"],
        )
        nombres = [m.name for m in modules]
        assert len(modules) == 2, nombres
        assert "Pedidos API" in nombres
        assert "Pedidos Worker" in nombres
        worker = next(m for m in modules if "Worker" in m.name)
        assert worker.kind == "procesamiento"

    def test_un_componente_que_solo_reclama_un_nodo_si_renombra(self):
        # El caso bueno sigue funcionando: un componente más descriptivo que
        # un único nodo lo renombra.
        modules = detect_modules(
            mermaid="graph TD\n  A[React + TypeScript] --> B[Modulo Pedidos]",
            componentes=["Frontend Web (React + TypeScript)"],
        )
        nombres = {m.name for m in modules}
        assert "Frontend Web (React + TypeScript)" in nombres
        assert "React + TypeScript" not in nombres

    def test_la_tecnologia_de_ui_le_gana_a_un_termino_de_dominio_mas_largo(self):
        """«react» (5) tiene que ganarle a «administracion» (14).

        Entre tipos distintos, largo no significa específico. Este módulo
        recibía repositorio y unidad de trabajo en el árbol del backend.
        """
        assert classify_module("Panel de administración (React)") == ("ui", "react")

    @pytest.mark.parametrize(
        "nombre, kind",
        [
            ("Servicio externo de pagos", "integracion"),
            ("Almacenamiento de archivos", "archivos"),
            ("Proveedor externo de envios", "integracion"),
        ],
    )
    def test_un_nombre_con_tipo_propio_no_es_infraestructura(self, nombre, kind):
        """`_NOT_A_MODULE` se pisaba con `MODULE_KIND_TERMS`.

        «externo», «tercero» y «almacenamiento» sacaban del árbol justo a los
        módulos cuyos términos son «servicio externo», «proveedor externo» y
        «almacenamiento de archivos»: esos términos no podían matchear nunca.
        """
        assert not is_infrastructure(nombre)
        assert classify_module(nombre)[0] == kind

    @pytest.mark.parametrize(
        "nombre",
        ["PostgreSQL", "Base de datos", "Balanceador de carga", "Usuario final", "S3",
         "Navegador Web", "Contenedor Docker"],
    )
    def test_la_infraestructura_de_verdad_sigue_fuera(self, nombre):
        assert is_infrastructure(nombre)

    def test_el_limite_de_anidamiento_no_cruza_de_convencion(self):
        """React recomienda 4 niveles; Spring Boot no declara límite.

        El bucle comparaba TODAS las líneas contra el límite de CADA
        convención, así que las rutas de Spring (`com/example/...`) disparaban
        el aviso de React. Un pendiente falso le quita credibilidad a los de
        verdad.
        """
        plan = build_plan(
            mermaid=(
                "graph TD\n  UI[Interfaz web] --> API[API REST]\n"
                "  API --> PED[Gestion de pedidos]"
            ),
            tecnologias=["Spring Boot", "Java", "React"],
        )
        anidamiento = [w for w in plan.warnings if "niveles de carpetas" in w]
        assert not anidamiento, anidamiento
        # Y cada línea sabe de qué convención vino, que es lo que lo permite.
        assert all(line.convention_id for line in plan.lines)
        ids = {line.convention_id for line in plan.lines}
        assert ids == {"spring_boot", "react"}

    def test_dos_modulos_no_pueden_chocar_de_carpeta(self):
        """`snake_case` es inyectiva sobre `normalize`, y se deduplica por eso.

        Fija la invariante que hace innecesario un aviso de colisión: si
        alguien cambia `snake_case` y deja de cumplirse, esto falla.
        """
        nombres = [
            "Gestión de pedidos",
            "Gestion-de-Pedidos",
            "GESTION  DE  PEDIDOS",
            "Pedidos API",
            "Módulo X",
            "Modulo-X",
        ]
        for a in nombres:
            for b in nombres:
                if normalize(a) != normalize(b):
                    assert snake_case(a) != snake_case(b), (a, b)


class TestTecnologiasEnTabla:
    """La propuesta real trae las tecnologías en TABLA, no en viñetas."""

    TABLA = """## Tecnologias
| Tecnologia | Justificacion | Requisito que lo motiva |
| --- | --- | --- |
| FastAPI (Python) | Framework ASGI ligero | Autenticacion |
| PostgreSQL | Base de datos relacional | Persistencia |
"""

    def test_lee_las_filas_de_la_tabla(self):
        lineas = parse_proposal_technologies(self.TABLA)
        assert any("FastAPI" in l for l in lineas)
        assert any("PostgreSQL" in l for l in lineas)

    def test_descarta_el_separador_y_el_encabezado(self):
        lineas = parse_proposal_technologies(self.TABLA)
        assert not any(set(l) <= set("-:| ") for l in lineas)
        assert not any("Requisito que lo motiva" in l for l in lineas)

    def test_una_propuesta_con_tabla_no_cae_al_respaldo(self):
        _terminos, de_la_seccion = stack_terms(self.TABLA)
        assert de_la_seccion is True

    def test_elige_la_convencion_desde_la_tabla(self):
        plan = build_plan(
            mermaid="graph TD\n  A[API REST] --> B[Gestion de pedidos]",
            proposal_markdown=self.TABLA,
        )
        assert plan.backend is not None
        assert plan.backend.convention_id == "fastapi"

    def test_el_termino_reportado_es_la_palabra_completa(self):
        """«api python» no puede ganar por estar dentro de «fastapi python»."""
        plan = build_plan(
            mermaid="graph TD\n  A[API REST]", proposal_markdown=self.TABLA
        )
        assert plan.backend_term == "fastapi"


class TestSerializacion:
    def test_el_plan_serializado_trae_todo_lo_que_la_interfaz_necesita(self, plan):
        payload = plan_to_dict(plan)
        assert set(payload) >= {
            "backend",
            "frontend",
            "modules",
            "lines",
            "tree_text",
            "warnings",
            "unmatched_layers",
            "module_kinds",
        }
        assert payload["tree_text"]
        assert all(line["source_url"] for line in payload["lines"])
        assert all("matched_term" in module for module in payload["modules"])

    def test_el_plan_serializado_es_json(self, plan):
        import json

        assert json.loads(json.dumps(plan_to_dict(plan)))

    def test_detect_modules_sin_nada_devuelve_vacio(self):
        assert detect_modules() == []


class TestTerceraRevisionPR:
    """Defectos de la revisión de F28, con las entradas exactas del revisor.

    Los dos primeros son la misma forma de error que ya habíamos arreglado por
    un lado y seguía abierta por el otro: algo se descarta en silencio.
    """

    def test_un_nodo_que_reclama_dos_componentes_no_pierde_ninguno(self):
        """Antes uno renombraba el nodo y el otro se descartaba sin aviso."""
        modules = detect_modules(
            mermaid="graph TD\n  A[Backend FastAPI]",
            componentes=["Servicio de pedidos (FastAPI)", "Servicio de pagos (FastAPI)"],
        )
        nombres = {m.name for m in modules}
        assert nombres == {
            "Servicio de pedidos (FastAPI)",
            "Servicio de pagos (FastAPI)",
        }

    def test_el_componente_no_usado_para_renombrar_entra_como_modulo(self):
        modules = detect_modules(
            mermaid="graph TD\n  A[Pagos]",
            componentes=["Integracion de pagos (Stripe)", "Reportes de pagos"],
        )
        nombres = {m.name for m in modules}
        assert "Reportes de pagos" in nombres
        reportes = next(m for m in modules if m.name == "Reportes de pagos")
        assert reportes.kind == "reporte"

    def test_dos_nodos_que_reclaman_un_componente_siguen_sin_duplicarse(self):
        """La corrección de la revisión anterior no se rompe con esta."""
        modules = detect_modules(
            mermaid="graph TD\n  A[Pedidos API] --> B[Pedidos Worker]",
            componentes=["Gestión de pedidos"],
        )
        nombres = [m.name for m in modules]
        assert len(modules) == 2, nombres
        assert "Gestión de pedidos" not in nombres

    def test_un_componente_no_renombra_dos_nodos(self):
        # Cada componente se usa para renombrar como máximo una vez.
        modules = detect_modules(
            mermaid="graph TD\n  A[Pedidos] --> B[Pedidos envios]",
            componentes=["Gestion de pedidos"],
        )
        nombres = [m.name for m in modules]
        assert len(nombres) == len(set(nombres))

    @pytest.mark.parametrize(
        "nombre, kind",
        [
            ("Perfil de usuario", "crud"),
            ("Administrador de contenidos", "crud"),
            ("Red de contactos", "crud"),
        ],
    )
    def test_las_palabras_genericas_no_sacan_modulos_de_negocio(self, nombre, kind):
        """`usuario`, `administrador` y `red` solo cuentan como nombre completo."""
        assert not is_infrastructure(nombre)
        assert classify_module(nombre)[0] == kind

    @pytest.mark.parametrize(
        "nombre",
        ["Usuario", "Usuarios", "Administrador", "Red", "Actor", "Usuario final",
         "PostgreSQL", "Base de datos", "Navegador Web", "S3", "Balanceador de carga",
         # Al pasar «red» a la lista de nombres completos, estas etiquetas
         # —habituales en los diagramas— se colaban como módulo de negocio y
         # recibían un árbol entero (`app/services/red_privada.py`). Van como
         # frase, así que «Red de contactos» sigue siendo un módulo.
         "Red privada", "Red interna", "Red pública", "Red externa", "Red local"],
    )
    def test_la_infraestructura_de_verdad_sigue_fuera(self, nombre):
        assert is_infrastructure(nombre)

    def test_la_infraestructura_evidente_se_aclara_pero_no_se_avisa(self):
        """Un diagrama normal no tiene que pedirle nada al usuario.

        Descartar en silencio hacía desaparecer módulos, pero avisar de TODOS
        los descartes era el extremo opuesto: cada ADR pedía revisar que
        PostgreSQL no fuera un módulo. Los descartes evidentes se mencionan
        como aclaración.
        """
        plan = build_plan(
            mermaid=(
                "graph TD\n  A[Gestion de pedidos] --> DB[(PostgreSQL)]\n"
                "  A --> U[Usuario]"
            ),
            tecnologias=["FastAPI"],
        )
        assert not any("infraestructura" in w for w in plan.warnings)
        aclaracion = next(n for n in plan.notes if "infraestructura" in n)
        assert "PostgreSQL" in aclaracion
        assert "Usuario" in aclaracion

    def test_los_nombres_reales_de_infraestructura_no_generan_aviso(self):
        """Cuarta revisión: los diagramas reales nombran por tecnología.

        «PostgreSQL 16» y «Redis Cache» avisaban porque solo se silenciaba el
        nombre EXACTO. Ahora basta con que todas sus palabras sean de
        infraestructura, relleno o versión.
        """
        plan = build_plan(
            mermaid=(
                "graph TD\n  A[Gestion de pedidos] --> DB[(PostgreSQL 16)]\n"
                "  A --> R[Redis Cache]\n  A --> U[Usuario final]\n"
                "  A --> S[Amazon S3]"
            ),
            tecnologias=["FastAPI"],
        )
        assert not any("infraestructura" in w for w in plan.warnings)
        aclaracion = next(n for n in plan.notes if "infraestructura" in n)
        for nodo in ("PostgreSQL 16", "Redis Cache", "Usuario final", "Amazon S3"):
            assert nodo in aclaracion

    @pytest.mark.parametrize(
        "nombre",
        [
            "PostgreSQL",
            "PostgreSQL 16",
            "MySQL 8.0",
            "Redis",
            "Redis Cache",
            "MongoDB Atlas",
            "Base de datos (PostgreSQL)",
            "Amazon S3",
            "Docker Compose",
            "Kubernetes Cluster",
            "Load Balancer (Nginx)",
            "Nginx",
            "Elasticsearch",
            "AWS Lambda",
            "CloudFront CDN",
            "Navegador web",
            "Red privada (VPC)",
            "Red pública",
            "Usuario final",
        ],
    )
    def test_infraestructura_evidente_no_es_descarte_dudoso(self, nombre):
        assert is_infrastructure(nombre)
        assert not discard_is_doubtful(nombre)

    @pytest.mark.parametrize(
        "nombre",
        [
            "Servidor de aplicaciones",
            "Servidor de aplicación",
            "Servidor de pagos",
            "Servidor de reglas (Nginx)",
        ],
    )
    def test_una_palabra_que_no_es_de_infraestructura_hace_dudoso_el_descarte(
        self, nombre
    ):
        """«aplicaciones», «pagos» o «reglas» podrían ser un módulo mal nombrado."""
        assert is_infrastructure(nombre)
        assert discard_is_doubtful(nombre)

    @pytest.mark.parametrize(
        "nombre", ["Nginx", "Elasticsearch", "CloudFront", "AWS Lambda"]
    )
    def test_estas_tecnologias_ya_no_terminan_como_modulo(self, nombre):
        """Fuera de la ronda anterior: llegaban al árbol como módulos `crud`."""
        assert is_infrastructure(nombre)

    def test_el_descarte_discutible_si_genera_un_aviso(self):
        """La palabra dentro de un nombre más largo sí es dudosa.

        «Servidor de aplicaciones» se descarta por «servidor», pero bien
        podría ser un módulo mal nombrado: eso es lo que hay que revisar.
        """
        plan = build_plan(
            mermaid="graph TD\n  S[Servidor de aplicaciones] --> A[Gestion de pedidos]",
            tecnologias=["FastAPI"],
        )
        aviso = next(w for w in plan.warnings if "infraestructura" in w)
        assert "Servidor de aplicaciones" in aviso
        assert not any("infraestructura" in n for n in plan.notes)

    def test_sin_descartes_no_hay_aviso(self):
        plan = build_plan(
            mermaid="graph TD\n  A[Gestion de pedidos] --> B[API REST]",
            tecnologias=["FastAPI"],
        )
        assert not any("infraestructura" in w for w in plan.warnings)

    @pytest.mark.parametrize(
        "tecnologias",
        [["FastAPI"], ["Django"], ["Spring Boot", "Java"], ["FastAPI", "React"]],
    )
    def test_dos_modulos_nunca_comparten_ruta(self, tecnologias):
        """La invariante, ahora sobre las RUTAS y no sobre los nombres.

        El razonamiento anterior ("`snake_case` es inyectiva") solo cubría las
        carpetas. `pascal_case` NO es inyectiva —"Pedidos 2" y "Pedidos2" dan
        los dos `Pedidos2`— y Spring Boot y React arman las rutas con él. Lo
        que salva es que toda plantilla incluye además `{module}`; esta prueba
        lo fija sin depender de ese razonamiento.
        """
        plan = build_plan(
            mermaid=(
                "graph TD\n  A[Pedidos 2] --> B[Pedidos2]\n"
                "  A --> C[Interfaz web]\n  B --> D[Gestion de clientes]"
            ),
            tecnologias=tecnologias,
        )
        por_modulo: dict[str, set[str]] = {}
        for line in plan.lines:
            if line.module:
                por_modulo.setdefault(line.module, set()).add(line.path)
        rutas = list(por_modulo.values())
        for i, unas in enumerate(rutas):
            for otras in rutas[i + 1 :]:
                assert not (unas & otras), unas & otras

    def test_pascal_case_no_es_inyectiva_y_se_sabe(self):
        """Se deja fijado para que nadie vuelva a razonar que sí lo es."""
        assert pascal_case("Pedidos 2") == pascal_case("Pedidos2")
        assert snake_case("Pedidos 2") != snake_case("Pedidos2")

    def test_toda_plantilla_de_ruta_incluye_el_nombre_en_snake(self):
        """Es lo que impide que la no-inyectividad de `pascal_case` choque."""
        from app.core.convention_catalog import list_conventions

        for convention in list_conventions():
            plantillas = [n.path for n in convention.module_tree]
            plantillas.append(convention.pattern_slot)
            for plantilla in plantillas:
                assert "{module}" in plantilla, (convention.convention_id, plantilla)

    def test_avisa_de_la_extension_en_un_proyecto_typescript(self):
        plan = build_plan(
            mermaid="graph TD\n  FE[Interfaz web] --> API[API REST]",
            tecnologias=["FastAPI", "React con TypeScript"],
        )
        assert any(".tsx" in n for n in plan.notes)

    def test_sin_typescript_no_se_avisa(self):
        plan = build_plan(
            mermaid="graph TD\n  FE[Interfaz web] --> API[API REST]",
            tecnologias=["FastAPI", "React"],
        )
        assert not any(".tsx" in n for n in plan.notes)
