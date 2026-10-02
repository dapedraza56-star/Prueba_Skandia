"""Orquesta el triage: contexto -> modelo -> validacion -> (correccion) -> resultado o modo degradado.

Garantias:
- El resultado SIEMPRE cumple el esquema, aunque el modelo falle (modo degradado).
- Nunca se ejecuta una accion: solo se sugiere un runbook del catalogo, con aprobacion humana.
- Todo queda trazado en "meta": estado, intentos, errores detectados, modelo y latencia.
"""
from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timezone

from . import prompts
from .contexto import Alerta, Elemento, a_dict
from .llm import ClienteLLM, ErrorModelo
from .validacion import advertencias, errores_esquema, validar

IMPACTO_POR_SEVERIDAD = {"Sev0": "critico", "Sev1": "alto", "Sev2": "medio", "Sev3": "bajo", "Sev4": "bajo"}


def triage_degradado(alerta: Alerta, motivo: str) -> dict:
    """Resumen minimo y honesto cuando no hay una salida confiable del modelo."""
    return {
        "version_esquema": "1.0",
        "que_esta_pasando": (f"Alerta {alerta.regla} ({alerta.severidad}): {alerta.descripcion}. "
                             "No hay un resumen automatico confiable; se requiere revision humana.")[:700],
        "impacto": {"nivel": IMPACTO_POR_SEVERIDAD.get(alerta.severidad, "medio"),
                    "descripcion": "Impacto estimado solo por la severidad de la alerta, sin analisis del modelo.",
                    "servicios_afectados": alerta.objetivos[:8]},
        "hipotesis": [{"descripcion": "Sin hipotesis automatica. Revisar el contexto adjunto.",
                       "probabilidad": "baja",
                       "evidencia": [{"referencia": "ALERTA-1", "cita": alerta.descripcion[:300] or alerta.regla}]}],
        "accion_sugerida": {"runbook": "RB-00-ESCALAR",
                            "justificacion": f"Triage automatico no disponible ({motivo[:200]}).",
                            "requiere_aprobacion_humana": True},
        "confianza": 0.0,
        "datos_faltantes": [f"Resumen del modelo no disponible: {motivo[:150]}"],
    }


def ejecutar_triage(alerta: Alerta, contexto: list[Elemento], cliente: ClienteLLM,
                    max_intentos: int = 2) -> dict:
    textos = {e.id: e.texto for e in contexto}
    msgs = prompts.mensajes(alerta, contexto)
    historial_errores: list[dict] = []
    inicio = time.perf_counter()
    triage, estado, motivo = None, "degradado", ""

    for intento in range(1, max_intentos + 1):
        try:
            respuesta = cliente.completar(msgs)
        except ErrorModelo as e:
            motivo = str(e)
            historial_errores.append({"intento": intento, "tipo": e.motivo, "errores": [str(e)]})
            break  # timeout, red o 4xx: no se insiste, se degrada (los reintentos de red viven en el cliente)
        obj, errores = validar(respuesta, textos)
        if not errores:
            triage, estado = obj, ("valido" if intento == 1 else "corregido")
            break
        historial_errores.append({"intento": intento, "tipo": "validacion", "errores": errores})
        motivo = f"salida invalida tras {intento} intento(s): {errores[0]}"
        msgs = msgs + [{"role": "assistant", "content": respuesta}, prompts.mensaje_correccion(errores)]

    if triage is None:
        triage = triage_degradado(alerta, motivo or "sin respuesta")
        assert not errores_esquema(triage), "el modo degradado debe cumplir el esquema"

    contexto_json = json.dumps(a_dict(contexto), ensure_ascii=False, sort_keys=True)
    return {
        "triage": triage,
        "meta": {
            "estado": estado,
            "intentos": len(historial_errores) + (0 if estado == "degradado" else 1),
            "errores_detectados": historial_errores,
            "advertencias": advertencias(triage) if estado != "degradado" else [],
            "modelo": getattr(cliente, "modelo", "desconocido"),
            "latencia_ms": round(1000 * (time.perf_counter() - inicio)),
            "alerta": {"id": alerta.id, "regla": alerta.regla, "severidad": alerta.severidad,
                       "disparada_local": alerta.disparada_local.isoformat()},
            "contexto": {"elementos": len(contexto), "sha256": hashlib.sha256(contexto_json.encode()).hexdigest()[:16]},
            "generado_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "nota": "Sugerencia para una persona. Este componente no ejecuta acciones.",
        },
    }
