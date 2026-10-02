"""Azure Function (modelo de programacion v2 de Python): conecta el triage con la alerta del Reto 3.

Flujo:
  Alerta de Azure Monitor --(Action Group, webhook con esquema comun)--> POST /api/triage
    -> contexto desde Log Analytics (KQL, identidad administrada)
    -> triage con el modelo (clave desde Key Vault, por referencia en App Settings)
    -> resultado registrado en Application Insights y enviado al canal del NOC (opcional)
  Nadie ni nada ejecuta acciones aqui: la persona de guardia lee la sugerencia y decide.

App Settings (ninguno es un secreto en texto plano):
  LOG_ANALYTICS_WORKSPACE_ID   id del workspace (GUID)
  TRIAGE_PROVEEDOR / TRIAGE_ENDPOINT / TRIAGE_MODELO
  TRIAGE_API_KEY               @Microsoft.KeyVault(SecretUri=https://<kv>.vault.azure.net/secrets/triage-api-key/)
  NOC_WEBHOOK_URL              opcional, tambien como referencia a Key Vault

Estado: base para el Reto 3. Pendiente de desplegar y validar contra el workspace real.
Despliegue: scripts/empaquetar.ps1 copia el paquete triage/ y los JSON al lado de este archivo.
"""
from __future__ import annotations

import json
import logging
import os

import azure.functions as func
import requests

from triage.contexto import Alerta, FuenteLogAnalytics, construir_contexto
from triage.llm import cliente_desde_entorno
from triage.motor import ejecutar_triage, triage_degradado

app = func.FunctionApp(http_auth_level=func.AuthLevel.FUNCTION)   # exige la clave de la funcion en la URL


def _publicar_en_noc(resultado: dict) -> None:
    url = os.getenv("NOC_WEBHOOK_URL")
    if not url:
        return
    t, m = resultado["triage"], resultado["meta"]
    texto = (f"Triage {m['alerta']['regla']} ({m['alerta']['severidad']}) - estado {m['estado']}\n"
             f"{t['que_esta_pasando']}\nAccion sugerida (requiere aprobacion): {t['accion_sugerida']['runbook']} "
             f"- confianza {t['confianza']:.2f}")
    try:
        requests.post(url, json={"text": texto}, timeout=10)
    except requests.RequestException:
        logging.exception("No se pudo publicar en el canal del NOC")   # no bloquea el triage


@app.route(route="triage", methods=["POST"])
def triage(req: func.HttpRequest) -> func.HttpResponse:
    try:
        alerta = Alerta.desde_esquema_comun(req.get_json())
    except ValueError as e:
        return func.HttpResponse(json.dumps({"error": str(e)}), status_code=400, mimetype="application/json")

    # Azure Monitor envia tambien la notificacion de "Resolved": no se hace triage de eso
    if (req.get_json()["data"]["essentials"].get("monitorCondition") or "Fired") != "Fired":
        return func.HttpResponse(status_code=204)

    try:
        fuente = FuenteLogAnalytics(os.environ["LOG_ANALYTICS_WORKSPACE_ID"])
        contexto = construir_contexto(alerta, fuente)
        resultado = ejecutar_triage(alerta, contexto, cliente_desde_entorno())
    except Exception as e:  # noqa: BLE001  (ErrorModelo, Log Analytics caido, config faltante: nunca dejar la alerta sin respuesta)
        logging.exception("Triage degradado")
        resultado = {"triage": triage_degradado(alerta, f"{type(e).__name__}: {e}"),
                     "meta": {"estado": "degradado", "alerta": {"id": alerta.id, "regla": alerta.regla,
                                                                 "severidad": alerta.severidad}}}

    # Log estructurado: queda consultable en Application Insights (traces) desde el tablero del Reto 3
    logging.info("triage_resultado %s", json.dumps({"meta": resultado["meta"],
                                                    "runbook": resultado["triage"]["accion_sugerida"]["runbook"],
                                                    "confianza": resultado["triage"]["confianza"]}, ensure_ascii=False))
    _publicar_en_noc(resultado)
    return func.HttpResponse(json.dumps(resultado, ensure_ascii=False), status_code=200, mimetype="application/json")
