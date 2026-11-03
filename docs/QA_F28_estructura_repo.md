# QA manual — F28: estructura del repositorio

Guion para probar la rama `feat/estructura-repo-convenciones` de punta a punta.

Cubre lo que las pruebas automáticas **no** pueden ver: que el árbol se lea
bien, que los enlaces abran, que el ADR no quede ilegible en modo oscuro, y
que la funcionalidad anterior no se haya degradado.

Marcá cada casilla. Si algo falla, anotá el caso y el síntoma.

---

## 0. Preparación

```powershell
docker compose up -d --build backend
docker compose logs backend --tail 20          # que uvicorn haya arrancado
docker compose exec backend python scripts/seed_patterns.py
docker compose build spa; docker compose up -d spa
```

- [ ] **0.1** El seed lista los **23 patrones** (19 de antes + Repository,
      Service Layer, Unit of Work, DTO).
- [ ] **0.2** El seed lista las **4 convenciones**: `FastAPI [backend]`,
      `React [frontend]`, `Django [backend]`, `Spring Boot [backend]`.
- [ ] **0.3** La línea de cobertura sale como **WARN** y dice exactamente
      `archivos, mensajeria, notificaciones`.
      Si sale como **ERROR**, la lista cambió y hay que actualizar
      `KNOWN_UNCOVERED_MODULE_KINDS`. Avisá antes de seguir.
- [ ] **0.4** `backend: 3 convención(es) indexada(s)` y `frontend: 1`.
- [ ] **0.5** La tabla existe:
      `docker compose exec postgres-app psql -U asistente -d asistente_db -c "select convention_id, layer from repo_convention_chunks order by 1"`
      → cuatro filas.

---

## 1. La puerta: sin diagrama aprobado no hay árbol

Creá un proyecto nuevo y llegá hasta Refinamiento **sin aprobar** el diagrama.

- [ ] **1.1** En Refinamiento, debajo del panel de despliegue, aparece
      **Estructura del repositorio**.
- [ ] **1.2** Dice «Aprueba primero el diagrama de arquitectura» y **no**
      muestra el botón de generar.
- [ ] **1.3** Aprobá el diagrama. Ahora sí aparece el botón
      **Generar estructura**.

---

## 2. Camino feliz: FastAPI + React

Proyecto nuevo. Descripción para pegar en la elicitación:

> Sistema web para una tienda que gestiona pedidos, clientes e inventario.
> Tiene una interfaz web, autenticación de usuarios, reportes de ventas,
> integración con una pasarela de pagos y notificaciones por correo.
> El backend es FastAPI sobre PostgreSQL y el frontend es React con TypeScript.

Importante: que la propuesta aprobada tenga una sección **Tecnologías** que
nombre FastAPI y React. De ahí sale la convención.

Aprobá propuesta → aprobá diagrama → aprobá despliegue → **Generar estructura**.

- [ ] **2.1** Arriba se nombran las dos convenciones, cada una con el término
      que la reconoció: `(reconocida por «fastapi»)` y `(reconocida por «react»)`.
- [ ] **2.2** El enlace de cada convención abre la documentación oficial
      (fastapi.tiangolo.com y legacy.reactjs.org). **Hacé clic en los dos.**
- [ ] **2.3** El árbol muestra las carpetas **anidadas de verdad**:
      ```
      app/
          repositories/
              gestion_de_pedidos.py
      ```
      No líneas sueltas sangradas sin su carpeta padre. *(Este fue un bug real
      de la primera versión.)*
- [ ] **2.4** No hay ningún `{module}`, `{role_dir}` ni `{Role}` sin reemplazar.
- [ ] **2.5** Las carpetas van antes que los archivos en cada nivel.
- [ ] **2.6** Hay una carpeta por módulo del diagrama, y **ninguna** que se
      llame `PostgreSQL`, `Usuario`, `Balanceador` o similar.

---

## 3. Lo que sostiene la historia: cada línea con su fuente

En la tabla **Por qué cada carpeta está ahí**:

- [ ] **3.1** **Toda** fila tiene un enlace en la columna «Razón y fuente».
      Recorré la tabla entera; si una sola fila no lo tiene, es un fallo del
      criterio de aceptación.
- [ ] **3.2** La columna «Sale de» distingue dos cosas: filas que dicen
      **Convención del stack** y filas que nombran un patrón
      (`Repository`, `Service Layer`, `Data Transfer Object (DTO)`).
- [ ] **3.3** `app/routers/<modulo>.py` sale de la **convención** (docs de FastAPI).
- [ ] **3.4** `app/services/<modulo>.py` sale del **patrón** Service Layer
      (martinfowler.com). Esto es a propósito: los docs oficiales de FastAPI
      **no** documentan `services/`, así que no se les atribuye.
- [ ] **3.5** Abrí tres enlaces de patrón al azar: tienen que llevar a Fowler
      o a Microsoft Learn, y la página tiene que existir.

---

## 4. Los módulos, uno por uno

En **Módulos detectados**, desplegá cada uno:

- [ ] **4.1** Cada módulo muestra su tipo y el término que lo decidió:
      `crud · por «gestion»`, `integracion · por «pasarela de pagos»`.
- [ ] **4.2** «Integración con pasarela de pagos» quedó como **integracion**,
      no como crud. *(Gana el término más largo; si dijera crud, le habría
      ganado «pagos» a «pasarela de pagos».)*
- [ ] **4.3** Al desplegar un módulo, cada patrón muestra **dónde queda**, la
      **razón** y el **enlace** a su fuente.
- [ ] **4.4** El módulo de **notificaciones** sale en amarillo diciendo que no
      hay patrón aplicable en la base.
      **Esto es lo correcto, no un bug**: es el hueco de cobertura declarado.
      Lo que sería un bug es que le asignara un patrón cualquiera.
- [ ] **4.5** Ese mismo aviso aparece en el bloque **Pendientes de revisar** de
      abajo, **una sola vez** (no duplicado).

---

## 5. Otros stacks

### 5.1 Spring Boot

Proyecto nuevo, misma descripción pero cambiando las tecnologías a
**Spring Boot, Java y PostgreSQL**.

- [ ] **5.1.1** La convención reconocida es **Spring Boot**, no otra.
      *(Gana «spring boot» sobre «spring».)*
- [ ] **5.1.2** El árbol agrupa **por módulo**:
      `com/example/myapplication/gestion_de_pedidos/` con su
      `GestionDePedidosController.java`, `...Service.java`, `...Repository.java`.
- [ ] **5.1.3** **No hay carpetas duplicadas** de servicio o repositorio. Acá
      la documentación oficial de Spring ya nombra esos roles, así que la
      línea la pone la convención y el patrón solo la justifica.
- [ ] **5.1.4** Aun así, al desplegar el módulo, `Service Layer` y
      `Repository` aparecen como justificación con su fuente.

### 5.2 Django

Tecnologías: **Django y PostgreSQL**.

- [ ] **5.2.1** El árbol crea una **aplicación por módulo**
      (`gestion_de_pedidos/` con `models.py`, `views.py`, `urls.py`,
      `migrations/`, `tests.py`).
- [ ] **5.2.2** Las plantillas van en `<modulo>/templates/<modulo>/`
      (el subdirectorio con el mismo nombre, como pide la documentación).

### 5.3 Stack no reconocido

Tecnologías: **COBOL sobre AS/400**.

- [ ] **5.3.1** Generar devuelve un error legible: que no se reconoció el stack
      y que hay que revisar la sección de tecnologías.
- [ ] **5.3.2** **No** devuelve un árbol inventado ni un árbol vacío.
- [ ] **5.3.3** El panel no se rompe: el botón sigue habilitado para reintentar.

---

## 6. El ADR

Con la estructura ya generada, descargá el ADR en `.md` y en PDF.

- [ ] **6.1** Bajo **4. Diagrama de arquitectura** aparece la subsección
      **Estructura del repositorio**.
- [ ] **6.2** **No** apareció una sección «5.» nueva: las secciones siguen
      siendo 4, 5 (Referencias), 6 (Historial), 7. Si se renumeraron, se rompe
      el código que las busca por número.
- [ ] **6.3** El árbol está dentro de un bloque de código y se lee bien.
- [ ] **6.4** La tabla tiene las seis columnas: Módulo, Tipo, Patrón, Dónde
      queda, Por qué, Fuente. **Toda fila con fuente.**
- [ ] **6.5** Los módulos sin patrón se listan aparte con su razón.
- [ ] **6.6** En el **PDF**: la tabla no se corta a la mitad de una página de
      forma ilegible y el bloque del árbol no se desborda del margen.

### Modo oscuro

Acá es donde más hay que mirar, por el antecedente de las tablas invisibles.

- [ ] **6.7** Panel de estructura en modo oscuro: el fondo **no** queda blanco.
- [ ] **6.8** La cabecera de la tabla («Ruta», «Sale de», «Razón y fuente») se
      lee: texto y fondo con contraste distinto.
- [ ] **6.9** El bloque `<pre>` del árbol se lee (no texto gris sobre gris).
- [ ] **6.10** Los enlaces se distinguen del texto normal.
- [ ] **6.11** El ADR visualizado en modo oscuro: la subsección nueva y su
      tabla se leen igual que las demás.

---

## 7. Historial y repetición

- [ ] **7.1** Generá dos veces. Aparece **Versiones generadas** con dos
      entradas, cada una con fecha, cantidad de módulos y convenciones.
- [ ] **7.2** Salí del proyecto y volvé a entrar: el historial sigue ahí.
- [ ] **7.3** El botón dice «Volver a generar» una vez que ya hay un árbol.

---

## 8. Regresión: que no se haya degradado lo de antes

Esto es lo que más me preocupa de esta rama, porque los cuatro patrones nuevos
entraron a la **misma tabla del RAG** que usa la propuesta.

- [ ] **8.1** En un proyecto nuevo, la propuesta **no** recomienda
      «Repository», «Service Layer», «Unit of Work» ni «DTO» como estilo de
      arquitectura. El patrón principal tiene que seguir siendo un estilo
      (capas, hexagonal, microservicios, monolito modular…).
- [ ] **8.2** La **tabla de trade-offs** de la propuesta no tiene una fila con
      ninguno de esos cuatro. Comparar «Repository» contra «Microservicios» no
      le dice nada al usuario.
- [ ] **8.3** La propuesta sigue citando la misma cantidad de patrones que
      antes (no menos). *Si recomienda menos alternativas que antes, el
      sobre-pedido del retrieval se quedó corto: decímelo.*
- [ ] **8.4** La sección de **Referencias** del ADR no se llenó de enlaces a
      Fowler sobre Repository.
- [ ] **8.5** Un proyecto **CRUD simple** («sistema de inventario para una
      tienda pequeña, 3 desarrolladores») sigue recibiendo un estilo monolítico
      y no Repository. Este es el caso más expuesto: en un proyecto así los
      chunks de Repository puntúan alto en el RAG.
- [ ] **8.6** El diagrama de **despliegue en la nube** sigue funcionando igual
      (generar, aprobar, cerrar fase). No lo toqué, pero comparte el ADR y el
      panel de Refinamiento.
- [ ] **8.7** El panel **Diagramas** sigue mostrando el historial de
      arquitectura y de despliegue.

---

## 9. Casos borde

- [ ] **9.1** Proyecto con **un solo módulo**: el árbol sale igual, sin
      errores.
- [ ] **9.2** Proyecto **sin frontend** (solo API): no aparece la parte de
      React ni una carpeta `common/` suelta.
- [ ] **9.3** Diagrama con un nombre de módulo con **tilde o ñ**
      («Gestión de Pedidos»): la carpeta sale como `gestion_de_pedidos`.
- [ ] **9.4** Dos proyectos distintos a la vez: el historial de cada uno es el
      suyo y no se mezclan.
- [ ] **9.5** Un usuario no puede ver la estructura de un proyecto de otro
      (probá con dos cuentas si tenés).

---

## Qué anotar si algo falla

Para cada fallo: **el número del caso**, qué esperabas, qué pasó, y si hay
algo en `docker compose logs backend --tail 50`. Si es del panel, la consola
del navegador (F12 → Console).
