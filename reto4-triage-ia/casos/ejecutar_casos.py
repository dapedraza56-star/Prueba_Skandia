"""Ejecuta los casos de prueba contra el modelo REAL y guarda la evidencia.

    python casos/ejecutar_casos.py            (desde reto4-triage-ia/, con .env configurado)

Casos:
  A  Alerta de ejemplo del kit (5xx > 5 % a las 14:00): contexto completo.
  B  Pool detenido (14:40): contexto completo.
  C  Cebo para invencion: alerta de 503 a las 14:45 con SOLO el log de HTTP.sys como contexto.
     Ahi no esta la causa (OutOfMemory, despliegue): si el modelo la "adivina" sin poder citarla,
     el validador lo detecta.
  D  Falsa alarma (warnings DCOM de madrugada): se espera impacto bajo y escalar sin actuar.
  E  Invencion forzada (modelo simulado que responde con evidencia falsa), para mostrar la deteccion
     de forma reproducible aunque el modelo real no se equivoque ese dia.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))

from dotenv import load_dotenv  # noqa: E402

from triage.contexto import Alerta, FuenteKit, construir_contexto  # noqa: E402
from triage.llm import ClienteSimulado, ErrorModelo, cliente_desde_entorno  # noqa: E402
from triage.motor import ejecutar_triage  # noqa: E402

KIT = BASE.parent / "kit_prueba_portalpagos" / "alertas"
EVID = BASE / "evidencias"

CASOS = [
    ("A", "Alerta de ejemplo (5xx 14:00)", KIT / "alerta_ejemplo.json", None),
    ("B", "Pool detenido (14:40)", BASE / "casos" / "alerta_pool_detenido.json", None),
    ("C", "Cebo: solo HTTP.sys como contexto", BASE / "casos" / "alerta_contexto_pobre.json", {"httperr"}),
    ("D", "Falsa alarma DCOM (madrugada)", BASE / "casos" / "alerta_falsa_dcom.json", None),
]

INVENTADA = {
    "version_esquema": "1.0",
    "que_esta_pasando": "El portal devuelve errores 5xx porque la base de datos SQL no responde y agota las conexiones.",
    "impacto": {"nivel": "alto", "descripcion": "Clientes sin poder pagar.", "servicios_afectados": ["PortalPagos"]},
    "hipotesis": [{"descripcion": "Timeouts de SQL Server agotan el pool de conexiones.", "probabilidad": "alta",
                   "evidencia": [{"referencia": "EV-L306", "cita": "System.Data.SqlClient.SqlException: Timeout expired"},
                                 {"referencia": "EV-L9999", "cita": "SQL Server is not responding"}]}],
    "accion_sugerida": {"runbook": "RB-02-RECICLAR-POOL", "justificacion": "Liberar conexiones a la base de datos.",
                        "requiere_aprobacion_humana": True},
    "confianza": 0.9, "datos_faltantes": [],
}


def correr(codigo, nombre, ruta, fuentes, cliente):
    alerta = Alerta.desde_esquema_comun(json.loads(ruta.read_text(encoding="utf-8")))
    contexto = construir_contexto(alerta, FuenteKit(fuentes))
    r = ejecutar_triage(alerta, contexto, cliente)
    r["caso"] = {"codigo": codigo, "nombre": nombre, "fuentes": sorted(fuentes) if fuentes else "todas"}
    r["contexto"] = [{"id": e.id, "texto": e.texto} for e in contexto]
    (EVID / f"caso_{codigo}.json").write_text(json.dumps(r, ensure_ascii=False, indent=2), encoding="utf-8")
    return r


def main():
    load_dotenv(BASE / ".env")
    EVID.mkdir(exist_ok=True)
    try:
        cliente = cliente_desde_entorno()
    except ErrorModelo as e:
        sys.exit(f"Configura el modelo antes de ejecutar los casos reales: {e}")

    filas = []
    for codigo, nombre, ruta, fuentes in CASOS:
        print(f"Caso {codigo}: {nombre}...", flush=True)
        filas.append(correr(codigo, nombre, ruta, fuentes, cliente))
    print("Caso E: invencion forzada (modelo simulado)...")
    filas.append(correr("E", "Invencion forzada (simulado)", KIT / "alerta_ejemplo.json", None,
                        ClienteSimulado([json.dumps(INVENTADA)] * 2)))

    lineas = ["# Casos de prueba del triage", "",
              f"Modelo: `{cliente.modelo}` (casos A-D) y modelo simulado (caso E). Detalle completo en `caso_*.json`.", "",
              "| Caso | Estado | Intentos | Errores detectados | Runbook sugerido | Confianza | Latencia |",
              "|---|---|---|---|---|---|---|"]
    for r in filas:
        m, t = r["meta"], r["triage"]
        errores = sum(len(x["errores"]) for x in m["errores_detectados"])
        lineas.append(f"| {r['caso']['codigo']} · {r['caso']['nombre']} | {m['estado']} | {m['intentos']} | {errores} | "
                      f"{t['accion_sugerida']['runbook']} | {t['confianza']:.2f} | {m['latencia_ms']} ms |")
    lineas += ["", "## Errores detectados por el validador", ""]
    for r in filas:
        for x in r["meta"]["errores_detectados"]:
            for e in x["errores"]:
                lineas.append(f"- **Caso {r['caso']['codigo']}**, intento {x['intento']}: {e}")
    (EVID / "resumen_casos.md").write_text("\n".join(lineas) + "\n", encoding="utf-8")
    print("\n".join(lineas))


if __name__ == "__main__":
    main()
