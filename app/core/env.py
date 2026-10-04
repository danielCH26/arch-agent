"""Lectura defensiva de configuración numérica desde variables de entorno."""

import logging
import os

logger = logging.getLogger(__name__)


def env_int(name: str, default: int, minimum: int = 0) -> int:
    """Devuelve un entero válido o el default sin impedir el arranque."""
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        if raw is not None:
            logger.warning("%s está vacío; se usa el valor por defecto %d", name, default)
        return default
    try:
        value = int(raw)
    except ValueError:
        logger.warning("%s=%r no es entero; se usa el valor por defecto %d", name, raw, default)
        return default
    if value < minimum:
        logger.warning("%s=%d es menor que %d; se usa el valor por defecto %d", name, value, minimum, default)
        return default
    return value
