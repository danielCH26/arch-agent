"""Normalización de texto libre para comparaciones deterministas.

Una sola implementación para los módulos que comparan lo que escribe el
usuario o el modelo con listas de palabras (propuesta, ADR, rúbrica, perfil
de dominio). Sin dependencias de base de datos para poder importarlo desde
cualquier lado.
"""

from __future__ import annotations

import unicodedata


# Algunos modelos (gpt-oss en Groq, entre otros) escriben "Trade‑offs" con un
# guion que no se parte (U+2011) y "Punto de decisión" con espacios que no se
# parten (U+00A0, U+202F). A la vista es igual, pero ninguna regex con "-" o
# " " lo encontraba: la propuesta se marcaba sin sección de trade-offs aunque
# la tuviera y había que regenerar. Se llevan a "-" y " " normales (los guiones
# largos – y — son puntuación, no se tocan). Los caracteres de ancho cero se
# quitan.
_UNICODE_FIXES = {
    **dict.fromkeys(map(ord, "\u2010\u2011\u2012\u2212\ufe63\uff0d"), "-"),
    **dict.fromkeys(
        map(ord, "\u00a0\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a\u202f\u205f\u3000"),
        " ",
    ),
    **dict.fromkeys(map(ord, "\u200b\u200c\u200d\u2060\ufeff"), None),
}


def normalize_text(text: str | None) -> str:
    """Minúsculas, sin acentos y con guiones y espacios comunes ("Trade‑offs" -> "trade-offs")."""
    return "".join(
        char
        for char in unicodedata.normalize("NFD", (text or "").translate(_UNICODE_FIXES).casefold())
        if unicodedata.category(char) != "Mn"
    )
