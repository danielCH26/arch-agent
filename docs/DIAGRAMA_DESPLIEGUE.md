# Diagrama de despliegue en la nube

Lleva una arquitectura ya aprobada a servicios reales de una nube y dibuja
cómo quedaría, con los logos oficiales y las conexiones entre servicios.

Depende de HU6: sin un diagrama de arquitectura **aprobado** no hay nada que
desplegar, y `POST /api/deployments/generate` responde 409.

---

## Qué se agregó

| Pieza | Dónde |
|---|---|
| Catálogo de servicios por nube | `data/cloud/aws.yaml`, `data/cloud/gcp.yaml` |
| Logos oficiales | `data/cloud/icons/<nube>/<servicio>.png` |
| Carga y validación del catálogo | `app/core/cloud_catalog.py` |
| Mapeo componente → servicio | `app/core/deployment_mapper.py` |
| Generación del diagrama | `app/core/deployment_diagram.py` |
| API | `app/api/deployments.py` |
| Catálogo en el RAG | `migrations/0022_*.sql`, `scripts/seed_cloud_catalog.py` |
| Interfaz | `frontend/src/components/DeploymentPanel.tsx` |

## Cómo se pone en marcha

```bash
python migrations/run_migrations.py     # crea cloud_service_chunks
python scripts/seed_cloud_catalog.py    # indexa el catálogo en el RAG
```

El diagrama en sí **no** necesita el seed: lee el YAML del disco. El seed es
para que el catálogo sea consultable por búsqueda semántica, que es lo que
pide la historia ("cargar ese catálogo en el RAG como categoría nueva").

## Flujo del usuario

1. En **Refinamiento**, una vez aprobado el diagrama de arquitectura,
   aparece el panel "Despliegue en la nube".
2. Elige la nube entre las habilitadas.
3. "Generar diagrama de despliegue": se mapea cada componente, se dibuja y
   se guarda como una versión más en el historial.
4. Aprueba, pide cambios o rechaza.

---

## Tres decisiones que vale la pena poder defender

### 1. HTML + Puppeteer, no la librería `diagrams`

`diagrams` (la librería de Python que trae los íconos de AWS y GCP) necesita
el binario de **Graphviz**, que no está en `backend/Dockerfile`. Meterlo
obliga a reconstruir la imagen y suma dependencias del sistema.

El camino HTML → data URL → `puppeteer_navigate` + `puppeteer_screenshot` ya
existe en `agent.py` para los diagramas Mermaid, ya funciona en producción, y
devuelve un adjunto con la misma forma. Así el diagrama de despliegue hereda
sin código extra el historial de versiones y el flujo de aprobación.

De `diagrams` sí se tomaron los **íconos**: son los oficiales, el repositorio
es MIT y están vendorizados en `data/cloud/icons/` (688 KB en total). Para
cambiarlos basta reemplazar el PNG con el mismo nombre.

### 2. El mapeo es determinista, no lo hace el LLM

Cada servicio del catálogo declara los términos que lo disparan (`matches`) y
el mapeo elige el término **más específico** que aparezca en el nombre del
componente. Tres razones:

- **Reproducible**: el mismo proyecto da siempre el mismo diagrama. Con un
  modelo de por medio no se puede prometer eso en una demostración.
- **Auditable**: cada fila guarda el término exacto que la disparó
  (`matched_term`), así que se puede explicar por qué "Base de datos
  PostgreSQL" terminó en RDS.
- **No se cae**: no depende de que el modelo responda, ni de su cuota.

Lo que no matchea **no se inventa**: sale en `unmapped` y la interfaz lo
muestra. Para cubrir un caso nuevo se agregan términos al YAML, no código.

### 3. Si dos piezas no se conectan en esa nube, se mete el intermediario

La arquitectura suele dibujar "Frontend → Backend". En AWS eso no existe tal
cual: CloudFront no habla con ECS, habla con el balanceador o con API
Gateway, y ese con ECS.

En vez de dibujar una conexión que no existe, o de descartar la flecha
(perdiendo información de la arquitectura aprobada), se busca en el catálogo
un servicio que sí permita el salto y se agrega al diagrama, marcado como
"lo agrega el proveedor". Las conexiones imposibles que no tienen puente
quedan en `dropped_connections`.

---

## Agregar una nube nueva

1. `data/cloud/<id>.yaml` con el mismo esquema (está documentado campo por
   campo en `aws.yaml`).
2. Los PNG en `data/cloud/icons/<id>/<service_id>.png`.
3. `python scripts/seed_cloud_catalog.py`.

No hay que tocar código: `GET /api/deployments/providers` lee el directorio.
El catálogo se valida al cargar — categoría desconocida, tier no declarado o
un `connects_to` hacia un servicio inexistente descartan ese archivo y lo
registran, sin tumbar a los demás proveedores.

## Pruebas

```bash
pytest tests/core/test_cloud_catalog.py \
       tests/core/test_deployment_mapper.py \
       tests/core/test_deployment_diagram.py -q
```

Cubren: que cada servicio tenga su ícono y su nota de despliegue, que las dos
nubes cubran las mismas categorías básicas, que el catálogo roto se detecte
al cargar, que los componentes típicos caigan donde deben en las dos nubes,
que no se dibujen conexiones fuera de `connects_to`, y que la página del
diagrama sea autocontenida.
