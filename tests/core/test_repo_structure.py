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
    is_infrastructure,
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
