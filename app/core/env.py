"""Lectura defensiva de configuración numérica desde variables de entorno.

Una variable vacía, no numérica o fuera de rango nunca impide el arranque: se
registra un warning y se usa el valor por defecto. Los límites (``minimum``) son
inclusivos; un valor por debajo del mínimo NO se recorta al mínimo, vuelve al
default.
"""

import logging
import math
import os

logger = logging.getLogger(__name__)


def env_int(name: str, default: int, minimum: int = 0) -> int:
    """Devuelve un entero válido (>= ``minimum``) o el default sin impedir el arranque."""
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


def env_float(name: str, default: float, minimum: float = 0.0) -> float:
    """Como ``env_int`` pero para decimales; rechaza también ``nan`` e ``inf``."""
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        if raw is not None:
            logger.warning("%s está vacío; se usa el valor por defecto %g", name, default)
        return default
    try:
        value = float(raw)
    except ValueError:
        logger.warning("%s=%r no es numérico; se usa el valor por defecto %g", name, raw, default)
        return default
    if not math.isfinite(value):
        logger.warning("%s=%r no es un número finito; se usa el valor por defecto %g", name, raw, default)
        return default
    if value < minimum:
        logger.warning("%s=%g es menor que %g; se usa el valor por defecto %g", name, value, minimum, default)
        return default
    return value
