# Imágenes de los patrones (F29)

Cada patrón de `data/patterns/*.yaml` tiene una imagen ilustrativa. Se muestra
en la Base de patrones, en la propuesta (bloque "Patrón seleccionado" y una
miniatura por opción de trade-offs) y en el ADR (sección 3 y PDF).

## Dónde viven

- Archivos: `frontend/public/pattern-images/` (en el repo, no enlazados, para
  que no se rompan). La carpeta no se llama `patterns/` porque chocaría con la
  ruta `/patterns` de la SPA.
- Datos: campos `image`, `image_alt` e `image_source` del YAML, copiados a
  `architect_patterns` (migración 0022) por `scripts/seed_patterns.py`.

## Carga en la base

La migración 0022 crea las columnas vacías. El backend corre
`seed_patterns.py --images-only` en cada arranque (`docker-compose.yml`): copia
solo la imagen y su atribución, sin recalcular embeddings. En una base nueva
hace falta además el seed completo una vez:

```bash
docker compose exec -T backend python scripts/seed_patterns.py
```

Fuera de Docker, correr el mismo comando a mano después de migrar.

## Atribución

`image_source` lleva `titulo`, `autor`, `licencia` y `url`, y `modificada: true`
cuando la imagen de un tercero se adaptó (fondo, márgenes, recorte). Con ese
campo el pie dice "CC BY 4.0, adaptada", como exige CC BY.

- **CC BY-SA** (Hexagonal, SOA): se usan sin modificar. Si alguna vez se
  adaptan, la versión adaptada queda bajo la misma licencia: se deja `licencia`
  igual y se agrega `modificada: true`.
- **Diagramas propios** (`url: null`): `titulo` dice "Elaboración propia" y
  `licencia` es la del repositorio. El test
  `test_every_pattern_has_an_attributed_image` lo comprueba.

## Idioma

Las imágenes de terceros (Azure Architecture Center, Wikimedia Commons) se usan
en su idioma original, en inglés: traducirlas sería otra adaptación. Los
diagramas propios van en español. El `image_alt` siempre está en español.

## Legibilidad

La imagen se muestra con `max-h-64` en móvil y `max-h-96` desde `md`. Si el
texto de un diagrama no se lee a ese tamaño, se reemplaza por uno propio más
simple (pasó con Microservicios y MLOps). El clic abre la imagen en una pestaña
nueva, a tamaño completo.
