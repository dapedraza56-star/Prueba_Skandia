"""Validacion de la salida del modelo en tres capas.

1. Sintaxis: es JSON (se toleran bloques ```json``` alrededor).
2. Esquema: cumple esquema_triage.json (campos, tipos, catalogo cerrado de runbooks,
   aprobacion humana obligatoria).
3. Semantica (anti-invencion): cada evidencia cita un id que EXISTE en el contexto y
   su "cita" es un fragmento TEXTUAL de ese elemento. Si el modelo inventa un evento,
   una linea o una cifra que no esta en los datos, se detecta aqui.
"""
from __future__ import annotations

import json
import re
import unicodedata
from functools import lru_cache
from pathlib import Path

from jsonschema import Draft202012Validator

BASE = Path(__file__).resolve().parents[1]


@lru_cache
def esquema() -> dict:
    return json.loads((BASE / "esquema_triage.json").read_text(encoding="utf-8"))


@lru_cache
def catalogo() -> dict:
    return json.loads((BASE / "catalogo_runbooks.json").read_text(encoding="utf-8"))


def extraer_json(texto: str) -> dict:
    t = texto.strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", t, re.S)
    if m:
        t = m.group(1).strip()
    obj = json.loads(t)
    if not isinstance(obj, dict):
        raise ValueError("la respuesta no es un objeto JSON")
    return obj


def errores_esquema(obj: dict) -> list[str]:
    v = Draft202012Validator(esquema())
    return [f"esquema: {'/'.join(map(str, e.absolute_path)) or '(raiz)'}: {e.message}"
            for e in sorted(v.iter_errors(obj), key=lambda e: list(e.absolute_path))]


def _normalizar(s: str) -> str:
    s = unicodedata.normalize("NFKC", s).lower()
    s = s.replace("“", '"').replace("”", '"').replace("’", "'").replace("‘", "'")
    s = s.strip(" \"'")
    return " ".join(s.split())


def errores_semanticos(obj: dict, textos_por_id: dict[str, str]) -> list[str]:
    errores = []
    norm = {k: _normalizar(v) for k, v in textos_por_id.items()}
    for i, h in enumerate(obj.get("hipotesis", [])):
        validas = 0
        for j, ev in enumerate(h.get("evidencia", [])):
            ref, cita = ev.get("referencia", ""), ev.get("cita", "")
            donde = f"hipotesis[{i}].evidencia[{j}]"
            if ref not in norm:
                errores.append(f"invencion: {donde} cita '{ref}', que no existe en el contexto")
                continue
            # Se permite recortar con "..." pero cada tramo debe estar en el texto original
            tramos = [t for t in re.split(r"\.\.\.|…", _normalizar(cita)) if len(t.strip()) >= 3]
            if not tramos or any(_normalizar(t) not in norm[ref] for t in tramos):
                errores.append(f"invencion: {donde} la cita \"{cita[:80]}\" no aparece textualmente en {ref}")
                continue
            validas += 1
        if validas == 0:
            errores.append(f"sin_evidencia: hipotesis[{i}] no tiene ninguna evidencia verificable")
    return errores


def advertencias(obj: dict) -> list[str]:
    """No invalidan la salida, pero se muestran a la persona que decide."""
    adv = []
    rb = obj.get("accion_sugerida", {}).get("runbook")
    info = {r["id"]: r for r in catalogo()["runbooks"]}.get(rb, {})
    if info.get("riesgo", "").startswith("alto"):
        adv.append(f"La accion sugerida {rb} es de riesgo alto: la aprueba {info.get('aprueba')}")
    if obj.get("confianza", 0) >= 0.8 and obj.get("datos_faltantes"):
        adv.append("Confianza alta pese a declarar datos faltantes: revisar")
    probs = [h.get("probabilidad") for h in obj.get("hipotesis", [])]
    if obj.get("confianza", 0) >= 0.7 and "alta" not in probs:
        adv.append("Confianza alta sin ninguna hipotesis de probabilidad alta: revisar")
    return adv


def validar(texto: str, textos_por_id: dict[str, str]) -> tuple[dict | None, list[str]]:
    """Devuelve (objeto, errores). Si hay errores, el objeto no se debe usar."""
    try:
        obj = extraer_json(texto)
    except (ValueError, json.JSONDecodeError) as e:
        return None, [f"json: la respuesta no es JSON valido ({e.__class__.__name__}: {str(e)[:80]})"]
    errs = errores_esquema(obj)
    if errs:
        return obj, errs
    return obj, errores_semanticos(obj, textos_por_id)
