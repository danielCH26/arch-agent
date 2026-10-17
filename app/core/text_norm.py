"""Normalización de texto libre para comparaciones deterministas.

Una sola implementación para los módulos que comparan lo que escribe el
usuario o el modelo con listas de palabras (propuesta, ADR, rúbrica, perfil
de dominio). Sin dependencias de base de datos para poder importarlo desde
cualquier lado.
"""

from __future__ import annotations

import unicodedata


def normalize_text(text: str | None) -> str:
    """Minúsculas y sin acentos ("Tecnológico" -> "tecnologico")."""
    return "".join(
        char
        for char in unicodedata.normalize("NFD", (text or "").casefold())
        if unicodedata.category(char) != "Mn"
    )
