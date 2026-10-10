# Guía de prueba de punta a punta — F10: fuentes, tecnologías y diagramas por patrón

Cubre los cambios de la rama `feature/f10-fuentes-diagramas`:

| Cambio | Dónde se ve |
| --- | --- |
| Fuentes curadas por patrón (migración 0019, `seed_patterns.py`, citas, `CitationList`) | Tarjeta de la propuesta, debajo de "Fuentes RAG para los trade-offs" |
| 3 a 6 fuentes verificadas por patrón (académicas + documentación oficial) | Mismos enlaces; `data/patterns/*.yaml` |
| Tabla de tecnologías con "Requisito que lo motiva" | Sección "Tecnologias" de la propuesta |
| Plantilla de diagrama según el patrón principal aprobado; observabilidad opcional | Diagrama generado en el chat |

Regla del equipo: **correr el caso demo y el golden set (#108) antes y después**,
y comparar. Anota los resultados en la sección 6.

---

## 0. Preparación (una sola vez)

- [ ] Rama correcta: `git branch --show-current` → `feature/f10-fuentes-diagramas`
- [ ] Tests automáticos sin errores:
  ```powershell
  pytest tests/core
  cd frontend; npm test; cd ..
  ```
- [ ] **Golden set antes y después** (hazlo después del commit, con `git status` limpio; si no, el cambio de rama arrastra los archivos sin guardar y el "antes" sale contaminado):
  ```powershell
  git switch feature/patrones-diagramas
  python scripts/eval_pattern_retrieval.py --mode full -v > golden_antes.txt
  git switch feature/f10-fuentes-diagramas
  python scripts/eval_pattern_retrieval.py --mode full -v > golden_despues.txt
  ```
  Las fuentes no entran a los embeddings, así que **top-1 y top-3 deben salir
  idénticos**. Si cambian, hay un problema: no sigas con la demo y avisa.
- [ ] Stack reconstruido: `docker compose up -d --build`
- [ ] Migraciones aplicadas (se corren solas al arrancar el backend):
  `docker compose logs backend | Select-String "migraci"` → debe mencionar `0019_add_pattern_sources.sql` o `No hay migraciones pendientes.`
- [ ] Columna creada:
  ```powershell
  docker compose exec postgres-app psql -U asistente -d asistente_db -c "\d architect_patterns"
  ```
  → debe listar `fuentes | jsonb | not null | '[]'::jsonb`
- [ ] **Volver a sembrar los patrones** (igual que con la 0018; sin esto las fuentes salen vacías):
  ```powershell
  docker compose exec backend python scripts/seed_patterns.py
  ```
  → `Patrones procesados: 19.`
- [ ] Cada patrón tiene al menos 3 fuentes en la base:
  ```powershell
  docker compose exec postgres-app psql -U asistente -d asistente_db -c "SELECT pattern_name, jsonb_array_length(fuentes) AS n FROM architect_patterns ORDER BY n, pattern_name;"
  ```
  → 19 filas, ninguna con `n` menor a 3. Si sale `0` en todas, no corriste el seed.
- [ ] Caso demo sembrado: `docker compose exec backend python scripts/seed_example.py`
- [ ] Hard refresh del navegador (Ctrl+Shift+R) y consola abierta (F12 → Network)
- [ ] Langfuse abierto (`http://localhost:3000`) para revisar el prompt del turno de diagrama (caso 3.4)

---

## 1. Caso principal: proyecto pequeño (debe salir capas o monolito modular)

### 1.1 Crear el proyecto

Nuevo proyecto en `http://localhost:5173`:

- **Nombre:** `Clínica Veterinaria Patitas`
- **Descripción:** `Sistema web para agendar citas, llevar la historia clínica de las mascotas y enviar recordatorios a los dueños.`

### 1.2 Elicitación — respuestas sugeridas

Responde a las preguntas del agente con estos datos (adapta el orden a lo que pregunte):

| Tema | Respuesta |
| --- | --- |
| Problema | Hoy las citas se llevan en un cuaderno y se pierden historias clínicas. |
| Usuarios | 2 veterinarios, 1 recepcionista y unos 300 dueños de mascotas; menos de 30 usuarios concurrentes. |
| Funcionalidades | Agendar y cancelar citas; historia clínica por mascota con vacunas; recordatorio por correo 24 h antes de la cita; reporte mensual de atenciones. |
| Equipo | 3 desarrolladores estudiantes, conocen Python y React. |
| Plazo | 4 meses. |
| Presupuesto | Bajo; preferimos servicios gratuitos u open source. |
| Calidad | Los datos clínicos deben estar protegidos con login por rol; disponibilidad en horario de la clínica. |
| Integraciones | Solo envío de correo. |

- [ ] Aprueba los requerimientos.

### 1.3 Propuesta — qué revisar

Genera la propuesta y verifica:

**Patrón principal**
- [ ] Es **Arquitectura en capas** o **Monolito modular** (equipo de 3, 4 meses, presupuesto bajo).
- [ ] No propone microservicios, broker de eventos, Kubernetes ni observabilidad centralizada como componentes.

**Tabla de Tecnologías**
- [ ] Hay **una tabla** con exactamente las columnas `Tecnología | Justificación | Requisito que lo motiva`.
- [ ] Como máximo 6 filas.
- [ ] Cada "Requisito que lo motiva" es un requisito **concreto de este proyecto** (p. ej. "recordatorio por correo 24 h antes", "login por rol para datos clínicos", "equipo conoce Python") y no una ventaja genérica ("es escalable", "es popular").
- [ ] Ninguna fila es CI/CD, Docker, servidor ASGI o librería de hash (salvo que la hayas pedido).

> Si la tabla **no aparece** o le falta la tercera columna, anótalo como hallazgo:
> hoy solo el prompt la exige; no hay un validador que la reintente.

**Trade-offs y fuentes**
- [ ] La tabla de trade-offs tiene 3 o más opciones y la columna `Fuente RAG` con `[1]`, `[2]`...
- [ ] Debajo de la propuesta aparece "Fuentes RAG para los trade-offs:" con `[1] <patrón>`, `[2] <patrón>`...
- [ ] **Debajo de cada patrón citado hay una lista de enlaces** (3 a 6 por patrón).
- [ ] Al hacer clic, el enlace abre en **pestaña nueva** y la página corresponde al título (paper, documentación o artículo).
- [ ] Inspecciona un enlace (clic derecho → Inspeccionar): tiene `target="_blank"` y `rel="noopener noreferrer"`.

### 1.4 Aprobar y pedir el diagrama

- [ ] Aprueba la propuesta.
- [ ] En el chat escribe: `Genera el diagrama de arquitectura de la propuesta aprobada`.

Verifica en la imagen generada:

- [ ] **Si el principal es capas:** el diagrama va de arriba a abajo `Cliente → Presentación → Aplicación/Negocio → Datos → Base de datos`, sin flechas que salten capas ni flechas hacia arriba.
- [ ] **Si el principal es monolito modular:** un bloque `Aplicación (un despliegue)` con un sub-bloque por módulo (Citas, Historia clínica, Recordatorios...) y **una sola** base de datos.
- [ ] El servicio de correo aparece como dependencia externa.
- [ ] **No aparece** ningún nodo de observabilidad, API Gateway, broker, balanceador, Docker ni CI/CD.
- [ ] No aparece el aviso amarillo de nodos no sustentados (grounding). Si aparece, anota qué nodos lista.
- [ ] Todos los nodos tienen nombres que están en la propuesta aprobada.

---

## 2. Variantes para probar otras plantillas

Mismo flujo (crear proyecto → elicitación → aprobar → propuesta → aprobar → diagrama).
Solo cambia la descripción y las respuestas clave.

### 2.1 Hexagonal

- **Descripción:** `Plataforma de pagos para comercios que debe integrarse con tres pasarelas (PSE, tarjetas y Nequi) y poder cambiar de pasarela sin tocar las reglas de negocio.`
- **Respuestas clave:** equipo de 5, 6 meses; las pasarelas cambian seguido; se necesitan pruebas automáticas de las reglas sin depender de las pasarelas.
- [ ] Principal esperado: **Hexagonal** (o Clean Architecture).
- [ ] Diagrama de izquierda a derecha con `Adaptadores de entrada → Núcleo de dominio (puertos, casos de uso) → Adaptadores de salida`; un adaptador por pasarela.
- [ ] El dominio no tiene flechas hacia los adaptadores.

### 2.2 Orientada a eventos

- **Descripción:** `Sistema de monitoreo de cultivos con 2.000 sensores que envían lecturas cada minuto; varias áreas (alertas, reportes, riego automático) reaccionan a las mismas lecturas de forma independiente.`
- **Respuestas clave:** equipo de 8 con experiencia en sistemas distribuidos, 12 meses, presupuesto medio; picos de tráfico en la mañana.
- [ ] Principal esperado: **Orientada a eventos**.
- [ ] Diagrama `Productores -.evento.-> Broker -.evento.-> Consumidores`, con flechas punteadas etiquetadas con el nombre del evento.
- [ ] Un consumidor por área (Alertas, Reportes, Riego).

### 2.3 Pipeline de datos (plantilla nueva)

- **Descripción:** `Consolidar cada noche las ventas de 15 tiendas (archivos CSV y una base MySQL) en un tablero de indicadores para la gerencia.`
- **Respuestas clave:** equipo de 2, procesos por lotes una vez al día, sin tiempo real.
- [ ] Principal esperado: **ETL / ELT** (o Medallion).
- [ ] Diagrama `Fuentes → Extracción → Staging → Transformación y validación → Carga → Almacén analítico → Tablero`, con un orquestador que programa las etapas.

> Para cada variante, abre también 1 o 2 enlaces de las fuentes del patrón principal.

---

## 3. Casos borde

### 3.1 Pedir observabilidad explícitamente

Sobre el diagrama del caso 1: `Solicitar cambios` → `Agrega observabilidad`.

- [ ] Aparece **un solo** colector de observabilidad, al costado, con flechas punteadas.
- [ ] El resto del diagrama se conserva igual.

### 3.2 Diagrama sin propuesta aprobada

En un proyecto con propuesta generada pero **no aprobada**, pide el diagrama.

- [ ] Se genera igual, pero no debe imponer la forma de un patrón (no hay propuesta aprobada de dónde sacarlo).

### 3.3 Propuesta vieja (antes de la 0019)

Abre la propuesta del caso demo o una generada antes de esta rama.

- [ ] La lista de citas se ve normal **sin enlaces** y sin errores en consola. Las propuestas viejas no guardaron fuentes; no es un bug.

### 3.4 Confirmar la plantilla en el prompt (Langfuse)

En Langfuse abre la traza del turno de diagrama del caso 1 → system prompt.

- [ ] Contiene `PLANTILLA DEL PATRON PRINCIPAL APROBADO (Arquitectura en capas)` (o `Monolito modular`, según el caso 1).
- [ ] Contiene **una sola** línea `PLANTILLA DEL PATRON PRINCIPAL APROBADO`.
- [ ] En el caso 3.2 esa línea **no** aparece.

---

## 4. Caso demo (regresión)

- [ ] Inicia sesión con el usuario demo y abre `Sistema de Gestión de Tareas`.
- [ ] Recorre las fases y regenera la propuesta.
- [ ] El patrón principal sigue siendo **Arquitectura en capas** (el mismo que antes del cambio).
- [ ] Las citas ahora muestran enlaces.
- [ ] El diagrama se genera sin errores.

---

## 5. Enlaces antes de la demo

Abre cada URL de las fuentes del patrón que vas a mostrar. La lista completa
está en `docs/FUENTES_Y_DIAGRAMAS_POR_PATRON.md` y en `data/patterns/*.yaml`.
Todas abrían el 2026-10-10, pero los sitios cambian.

- [ ] Enlaces del patrón principal del caso 1 abiertos y correctos.
- [ ] Enlaces de los patrones de las variantes que vas a mostrar.

---

## 6. Registro de resultados

| Prueba | Antes | Después | OK |
| --- | --- | --- | --- |
| `pytest tests/core` | | | |
| `npm test` | | | |
| Golden set top-1 (`--mode full`) | | | |
| Golden set top-3 (`--mode full`) | | | |
| Caso demo: patrón principal | Capas | | |
| Caso 1: patrón principal | — | | |
| Caso 1: tabla de tecnologías con 3 columnas | — | | |
| Caso 1: enlaces visibles y abren | — | | |
| Caso 1: diagrama con la forma de la plantilla | — | | |
| Caso 1: sin observabilidad ni gateway | — | | |
| 2.1 Hexagonal | — | | |
| 2.2 Eventos | — | | |
| 2.3 ETL | — | | |
| 3.1 Observabilidad pedida | — | | |
| 3.4 Plantilla en Langfuse | — | | |

**Hallazgos:**

-
