"""Linea de comandos.

    python -m triage --alerta ../kit_prueba_portalpagos/alertas/alerta_ejemplo.json
    python -m triage --alerta casos/alerta_pool_detenido.json --fuentes httperr --salida evidencias/x.json

Lee la configuracion del modelo de variables de entorno o de un archivo .env (ver .env.ejemplo).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .contexto import Alerta, FuenteKit, construir_contexto
from .llm import ErrorModelo, cliente_desde_entorno
from .motor import ejecutar_triage, triage_degradado


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="triage", description="Triage de una alerta de Azure Monitor con IA")
    ap.add_argument("--alerta", required=True, type=Path, help="JSON en el esquema comun de Azure Monitor")
    ap.add_argument("--fuentes", default="eventos,iis,httperr,perfmon,cambios",
                    help="fuentes de contexto del kit, separadas por coma")
    ap.add_argument("--antes", type=int, default=30, help="minutos de contexto antes de la alerta")
    ap.add_argument("--despues", type=int, default=5, help="minutos de contexto despues de la alerta")
    ap.add_argument("--salida", type=Path, help="archivo donde guardar el resultado JSON")
    args = ap.parse_args(argv)

    try:
        from dotenv import load_dotenv  # noqa: PLC0415
        load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    except ImportError:
        pass

    alerta = Alerta.desde_esquema_comun(json.loads(args.alerta.read_text(encoding="utf-8")))
    contexto = construir_contexto(alerta, FuenteKit(set(args.fuentes.split(","))), args.antes, args.despues)
    try:
        cliente = cliente_desde_entorno()
    except ErrorModelo as e:
        # Sin modelo configurado igual se entrega un resultado valido (modo degradado)
        resultado = {"triage": triage_degradado(alerta, str(e)), "meta": {"estado": "degradado", "motivo": str(e)}}
    else:
        resultado = ejecutar_triage(alerta, contexto, cliente)
    resultado["contexto"] = [{"id": e.id, "texto": e.texto} for e in contexto]

    texto = json.dumps(resultado, ensure_ascii=False, indent=2)
    if args.salida:
        args.salida.parent.mkdir(parents=True, exist_ok=True)
        args.salida.write_text(texto, encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    print(texto)
    return 0 if resultado["meta"]["estado"] != "degradado" else 3


if __name__ == "__main__":
    sys.exit(main())
