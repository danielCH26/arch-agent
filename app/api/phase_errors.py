"""Mapeo unico ``PhaseDecisionError`` -> ``HTTPException`` (REQ-SA-28, REQ-SA-34).

Todos los endpoints que pasan por ``record_decision`` o por el gate de
``/advance`` deben traducir los errores del core con ESTE helper, para que:

* un ``PhaseMismatchError`` (p.ej. pestana desactualizada) sea un 409 tipado y
  no un 500;
* el ``detail`` nunca lleve ``str(exc)`` (REQ-SA-34): se usa un cuerpo
  estructurado con el nombre de la clase como identificador estable.
"""

from __future__ import annotations

from fastapi import HTTPException, status

from app.core.phase_decisions import (
    InvalidActionError,
    InvalidPhaseError,
    PhaseDecisionError,
    PhaseMismatchError,
    PhaseNotApprovedError,
)


def phase_decision_http_error(exc: PhaseDecisionError) -> HTTPException:
    """Traduce un error del core a un ``HTTPException`` sin filtrar ``str(exc)``."""
    if isinstance(exc, PhaseMismatchError):
        # REQ-SA-28: typed 409 body.
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "phase_mismatch",
                "current_phase": exc.current_phase,
                "requested_phase": exc.requested_phase,
            },
        )
    if isinstance(exc, PhaseNotApprovedError):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": "phase_not_approved", "phase": exc.phase},
        )
    if isinstance(exc, (InvalidPhaseError, InvalidActionError)):
        return HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"error": "validation_error", "kind": type(exc).__name__},
        )
    return HTTPException(
        status_code=exc.http_status,
        detail={"error": "phase_decision_error", "kind": type(exc).__name__},
    )


# Detalle generico para el fallback 500: NUNCA ``str(exc)`` (REQ-SA-34).
INTERNAL_ERROR_DETAIL = {"error": "internal_error"}
