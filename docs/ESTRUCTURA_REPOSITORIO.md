# Estructura del repositorio (árbol de carpetas)

Issue **#119 [F28]**. Propone el árbol de carpetas del proyecto combinando la
convención oficial del stack con el patrón de diseño que aplica a cada módulo
detectado, y lo muestra como texto en la interfaz y en el ADR.

**Fuera de alcance** (igual que en la issue): no se generan archivos ni se
entrega un repositorio descargable. El entregable es el árbol y su
justificación.

---

## La decisión de diseño que sostiene todo

El árbol **no lo escribe el LLM**. Si lo escribiera, inventaría carpetas, y el
criterio de aceptación dice que nada puede ir sin respaldo del RAG.

La composición es determinista y cada línea carga su fuente:

1. Los **módulos** salen de los nodos del diagrama de arquitectura aprobado
   (se reusa `deployment_mapper.parse_mermaid_nodes`) y de los componentes de
   la propuesta. La infraestructura y los actores se descartan: no hay carpeta
   `PostgreSQL/`.
2. Cada módulo recibe un **tipo** (`crud`, `integracion`, `ui`…) por
   coincidencia de términos, y se guarda **el término que lo decidió**.
3. La **convención del stack** se elige por capa (backend y frontend),
   guardando también el término que la activó.
4. Se piden los **patrones** cuyo `applies_to_modules` incluye ese tipo, y sus
   aportes se ubican en la ranura que la convención define.
5. Toda línea sale con `source_title` y `source_url`.

El LLM puede redactar la prosa a partir de este plan, que ya trae los hechos y
las citas. No decide la estructura.

---

## Las dos fuentes de cada línea del árbol

Una línea puede venir de la **convención del stack** o de un **patrón**, y el
árbol lo distingue. Esto no es un detalle cosmético: es lo que evita
atribuirle a la documentación oficial algo que no dice.

Ejemplo concreto. La documentación oficial de FastAPI documenta
`app/routers/items.py`, pero **no** documenta `app/services/` ni
`app/repositories/`. Entonces:

- `app/routers/pedidos.py` → la trae la convención, citando los docs de FastAPI.
- `app/services/pedidos.py` → la aporta Service Layer, citando a Fowler.
- `app/repositories/pedidos.py` → la aporta Repository, citando a Fowler y a
  Microsoft Learn.

Spring Boot es el caso contrario: su listado oficial **ya nombra**
`{Modulo}Service.java` y `{Modulo}Repository.java`. Ahí la línea la pone la
convención y el patrón solo la justifica; no se duplica la carpeta. Eso es lo
que declara `documented_roles` en cada YAML de convención.

**Cuando un patrón aplica pero la convención no sabe dónde ponerlo**, se
reporta: «aplica, pero sin carpeta documentada». No se inventa una ruta.

---

## Archivos

### Datos

| Archivo | Qué trae |
|---|---|
| `data/conventions/fastapi.yaml` | Convención de FastAPI. **El esquema está documentado campo por campo acá.** |
| `data/conventions/spring_boot.yaml` | Spring Boot (la única cuya fuente ya nombra Service y Repository) |
| `data/conventions/django.yaml` | Django (una aplicación por módulo) |
| `data/conventions/react.yaml` | React (agrupado por feature; único con `nesting_limit`) |
| `data/patterns/repository.yaml` | **Nuevo** |
| `data/patterns/service_layer.yaml` | **Nuevo** |
| `data/patterns/unit_of_work.yaml` | **Nuevo** |
| `data/patterns/data_transfer_object.yaml` | **Nuevo** |

Los 19 patrones existentes recibieron `applies_to_modules`. `hexagonal.yaml`
recibió además `structure_contributions` (puertos y adaptadores).

### Código

| Archivo | Qué hace |
|---|---|
| `app/core/convention_catalog.py` | Carga y **valida** las convenciones. Un `source` que apunta a la nada hace que el YAML no cargue. |
| `app/core/repo_structure.py` | Detección de módulos, elección de patrones, composición y render del árbol. |
| `app/api/repo_structure.py` | `GET /conventions`, `POST /generate`, `GET /history`. |
| `app/core/pattern_catalog.py` | Nivel `modulo`, `applies_to_modules`, `structure_contributions`, auditoría de cobertura. |
| `app/core/adr_generator.py` | Subsección «Estructura del repositorio». |
| `frontend/src/api/repoStructure.ts` | Cliente. |
| `frontend/src/components/RepoStructurePanel.tsx` | Panel en Refinamiento. |
| `migrations/0023_add_repo_convention_chunks.sql` | Tabla `repo_convention_chunks`. |
| `scripts/seed_conventions.py` | Seed; `seed_patterns.py` lo llama al final. |

---

## Puesta en marcha

La migración `0023` se aplica **sola** al arrancar el backend: el `command` del
servicio en `docker-compose.yml` corre `scripts/init_db.py` y
`python -m migrations.run_migrations` antes de uvicorn.

```bash
docker compose up -d --build backend
docker compose logs backend     # "N migración(es) aplicada(s)."
```

El seed de convenciones **no** se corre solo. Hay que lanzarlo una vez:

```bash
docker compose exec backend python scripts/seed_patterns.py
# o, si solo cambiaron las convenciones:
docker compose exec backend python scripts/seed_conventions.py
```

> **Ojo con la forma del comando.** `python migrations/run_migrations.py` falla
> con `ModuleNotFoundError: No module named 'app'`: ese script importa
> `app.core.database` pero no mete la raíz del proyecto en `sys.path`. Dentro
> del contenedor funciona porque la imagen define `PYTHONPATH=/app`, y la forma
> correcta es `python -m migrations.run_migrations`. Es el hallazgo #9 de
> `docs/QA_feature-hu6-diagrama.md`; `docs/DIAGRAMA_DESPLIEGUE.md` todavía
> arrastra el comando viejo.

El seed reporta la cobertura de patrones por tipo de módulo. Si la lista de
huecos no coincide con la documentada, lo dice como `ERROR`.

---

## Nivel `modulo`: por qué existe

Repository, Service Layer, Unit of Work y DTO **no son estilos de
arquitectura**. Si entraran a la propuesta:

- la tabla de trade-offs compararía «Repository» contra «Microservicios», que
  no le dice nada al usuario;
- en un proyecto CRUD, sus chunks puntúan alto y podrían **desplazar al estilo
  real** del top-k.

Por eso llevan `level: modulo` y se descartan en `_retrieve_patterns`,
**antes** de recortar al top-k (sobre-pidiendo para compensar), con un segundo
filtro en `_eligible` por si otro camino llega a la selección. Los patrones de
nivel `codigo` (capas, hexagonal, clean, MVC) **siguen** disponibles para la
propuesta: el filtro solo saca `modulo`.

---

## La auditoría de cobertura, y lo que falta

De los 19 patrones originales, solo 5 son `level: codigo`; los otros 14 son de
despliegue o complemento y **no dicen nada sobre cómo se organizan las
carpetas dentro de un módulo**. Esos llevan `applies_to_modules: []` con el
comentario de por qué: forzarlos sería inventar una justificación que su
fuente no da.

La auditoría se **calcula** (`module_kinds_without_patterns()`) y se compara
contra `KNOWN_UNCOVERED_MODULE_KINDS`, que está escrita a mano con la razón de
cada hueco. Hay una prueba que falla si dejan de coincidir.

Hoy quedan tres tipos sin cobertura:

| Tipo | Por qué |
|---|---|
| `mensajeria` | Lo que hay sobre colas y eventos (Event-Driven, Saga, Event Sourcing) describe cómo se comunica el **sistema**, no cómo se ordenan las carpetas de un módulo. |
| `archivos` | No hay en la base ningún patrón de almacenamiento de archivos a nivel de módulo. |
| `notificaciones` | Igual: no hay patrón de módulo para esto. |

Para un módulo de estos el generador **lo dice** en lugar de inventar, y el
ADR lo lista aparte. Cerrarlos es trabajo de contenido —escribir los patrones
con sus fuentes—, no de código.

---

## Fuentes

Todas verificadas, ninguna inventada.

**Convenciones de carpetas (documentación oficial):**

- [Bigger Applications - Multiple Files](https://fastapi.tiangolo.com/tutorial/bigger-applications/) — FastAPI
- [Structuring Your Code](https://docs.spring.io/spring-boot/reference/using/structuring-your-code.html) — Spring Boot
- [Advanced tutorial: How to write reusable apps](https://docs.djangoproject.com/en/stable/intro/reusable-apps/) — Django
- [File Structure](https://legacy.reactjs.org/docs/faq-structure.html) — React

**Patrones de módulo:**

- [Repository](https://www.martinfowler.com/eaaCatalog/repository.html) — Fowler, *PoEAA*
- [Service Layer](https://martinfowler.com/eaaCatalog/serviceLayer.html) — Fowler, *PoEAA*
- [Unit of Work](https://martinfowler.com/eaaCatalog/unitOfWork.html) — Fowler, *PoEAA*
- [Data Transfer Object](https://martinfowler.com/eaaCatalog/dataTransferObject.html) y [Local DTO](https://martinfowler.com/bliki/LocalDTO.html) — Fowler
- [Design the infrastructure persistence layer](https://learn.microsoft.com/en-us/dotnet/architecture/microservices/microservice-ddd-cqrs-patterns/infrastructure-persistence-layer-design) — Microsoft Learn
- [Repository pattern (ASP.NET Core)](https://learn.microsoft.com/aspnet/core/fundamentals/repository-pattern) — Microsoft Learn

---

## Pruebas

| Archivo | Cubre |
|---|---|
| `tests/core/test_convention_catalog.py` | Que un YAML sin fuente **no cargue**; match por capa y por término más largo; un archivo roto no tumba a los demás. |
| `tests/core/test_repo_structure.py` | Que toda línea tenga fuente; que no se invente nada; el render del árbol; la detección de módulos. |
| `tests/core/test_pattern_module_levels.py` | La auditoría de cobertura; que los patrones nuevos tengan fuentes y `when_not_to_use`; que el nivel `modulo` quede fuera de la propuesta. |
| `tests/core/test_adr_repo_structure.py` | Que la sección sea subsección (no renumera el ADR) y que toda fila traiga fuente. |
| `frontend/src/components/__tests__/RepoStructurePanel.test.tsx` | Que cada línea enlace su fuente; que se distinga convención de patrón; errores sin romper el panel. |

### Dos errores que encontró la verificación

Vale dejarlos anotados porque son los que una prueba superficial no agarra:

1. **El árbol no emitía las carpetas intermedias.** La primera versión
   indentaba por profundidad: `app/repositories/pedidos.py` aparecía sangrado
   sin que `repositories/` apareciera nunca. Hay una prueba específica.
2. **Un `pattern_slot` sin marcador de rol colapsaba todos los patrones en la
   misma ruta.** Si la plantilla no trae `{role_dir}`, `{role_file}` ni
   `{Role}`, no puede distinguir un repositorio de un servicio: ahora se
   reporta como «sin ubicar» en lugar de devolver una ruta compartida.
