"""Calidad minima de la base de conocimiento curada (data/patterns/*.yaml).

F10 exige que la tabla de trade-offs cite ventajas y desventajas del RAG. Si el
YAML trae solo dos bullets de una linea por lado, el LLM no tiene de donde sacar
mecanismos ni impacto concreto y la tabla sale generica. Este test protege el
piso de contenido y que cada patron declare fuentes verificables.
"""

from pathlib import Path

import yaml

PATTERNS_DIR = Path(__file__).resolve().parents[2] / "data" / "patterns"
# Las imagenes se sirven desde el frontend: /pattern-images/x -> frontend/public/pattern-images/x
PUBLIC_DIR = Path(__file__).resolve().parents[2] / "frontend" / "public"

MIN_BULLETS = 4
MIN_WORDS_PER_BULLET = 10
# El chunk 'tradeoffs' se embebe con multilingual-e5-small (max 512 tokens). En
# espanol ~1.6 tokens/palabra: por encima de ~280 palabras el final se trunca.
MAX_TRADEOFFS_CHUNK_WORDS = 280


def _patterns():
    return [
        (path.name, yaml.safe_load(path.read_text(encoding="utf-8")))
        for path in sorted(PATTERNS_DIR.glob("*.yaml"))
    ]


def test_every_pattern_has_rich_tradeoffs():
    for filename, pattern in _patterns():
        tradeoffs = pattern["tradeoffs"]
        for side in ("ventajas", "desventajas"):
            bullets = tradeoffs[side]
            assert len(bullets) >= MIN_BULLETS, f"{filename}: {side} tiene {len(bullets)}"
            for bullet in bullets:
                assert len(bullet.split()) >= MIN_WORDS_PER_BULLET, (
                    f"{filename}: bullet demasiado corto en {side}: {bullet!r}"
                )


def test_tradeoffs_chunk_fits_embedding_window():
    for filename, pattern in _patterns():
        ventajas = "; ".join(pattern["tradeoffs"]["ventajas"])
        desventajas = "; ".join(pattern["tradeoffs"]["desventajas"])
        text = f"{pattern['pattern_name']} - ventajas: {ventajas}. Desventajas: {desventajas}."
        assert len(text.split()) <= MAX_TRADEOFFS_CHUNK_WORDS, (
            f"{filename}: chunk de trade-offs con {len(text.split())} palabras"
        )


def test_every_pattern_declares_verifiable_sources():
    for filename, pattern in _patterns():
        fuentes = pattern.get("fuentes")
        assert fuentes, f"{filename}: sin fuentes"
        for fuente in fuentes:
            assert fuente["titulo"].strip(), filename
            assert fuente["url"].startswith("https://"), f"{filename}: {fuente['url']}"


def test_every_pattern_has_an_attributed_image():
    for filename, pattern in _patterns():
        image = pattern.get("image")
        assert image, f"{filename}: sin image"
        # Guardadas en el repo (no enlazadas) para que no se rompan.
        assert image.startswith("/pattern-images/"), f"{filename}: {image}"
        assert (PUBLIC_DIR / image.lstrip("/")).is_file(), f"{filename}: no existe {image}"
        assert len(pattern.get("image_alt", "").split()) >= 8, f"{filename}: image_alt muy corto"
        source = pattern.get("image_source") or {}
        for key in ("titulo", "autor", "licencia"):
            assert (source.get(key) or "").strip(), f"{filename}: image_source sin {key}"
        url = source.get("url")
        assert url is None or url.startswith("https://"), f"{filename}: {url}"
        if url is None:
            assert source["licencia"] == "Elaboración propia", filename
