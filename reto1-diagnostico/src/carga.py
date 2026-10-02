"""Carga y normalizacion de las fuentes del kit de PortalPagos.

Decisiones (ver README del reto):
- Los logs W3C de IIS y de HTTP.sys se escriben en UTC (comportamiento por
  defecto de IIS). Se verifica con el encabezado del 14/09 (#Date 05:00 UTC =
  00:00 hora Colombia) y con el archivo u_ex260921, que solo llega a las 04:59 UTC.
  Todo se convierte a hora de Colombia (UTC-5, sin horario de verano).
- Eventos y Perfmon ya vienen en hora local del servidor (Bogota).
- El esquema de campos W3C cambia dentro de un mismo archivo (17/09 03:12 UTC se
  agregan cs-host y X-Forwarded-For); por eso se respeta cada directiva #Fields.
- Archivos con contenido identico (p.ej. "u_ex260916 - copia.log") se cargan una
  sola vez, comparando el hash SHA-256 del contenido.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import pandas as pd

OFFSET_CO = pd.Timedelta(hours=-5)  # Colombia: UTC-5 todo el año

RAIZ = Path(__file__).resolve().parents[2]
KIT = RAIZ / "kit_prueba_portalpagos"

# Clientes que no son usuarios reales
AGENTE_NOC = "NOC-HealthProbe"


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def archivos_unicos(paths: list[Path]) -> tuple[list[Path], list[tuple[Path, Path]]]:
    """Devuelve (archivos a cargar, [(descartado, original)]) sin duplicados de contenido."""
    vistos: dict[str, Path] = {}
    descartados = []
    for p in sorted(paths, key=lambda x: (len(x.name), x.name)):  # el nombre "limpio" primero
        h = _hash(p)
        if h in vistos:
            descartados.append((p, vistos[h]))
        else:
            vistos[h] = p
    return sorted(vistos.values()), descartados


def leer_w3c(path: Path) -> pd.DataFrame:
    """Lee un archivo W3C respetando cada directiva #Fields (el esquema puede cambiar)."""
    filas, campos = [], None
    with path.open(encoding="utf-8", errors="replace") as f:
        for n, linea in enumerate(f, start=1):
            linea = linea.rstrip("\r\n")
            if not linea:
                continue
            if linea.startswith("#"):
                if linea.startswith("#Fields:"):
                    campos = linea.split()[1:]
                continue
            valores = linea.split(" ")
            if campos is None or len(valores) != len(campos):
                continue  # linea corrupta: se cuenta aparte en calidad de datos
            fila = dict(zip(campos, valores))
            fila["_archivo"] = path.name
            fila["_linea"] = n
            filas.append(fila)
    return pd.DataFrame(filas)


def _a_hora_colombia(df: pd.DataFrame) -> pd.DataFrame:
    df["ts_utc"] = pd.to_datetime(df["date"] + " " + df["time"])
    df["ts"] = df["ts_utc"] + OFFSET_CO
    return df


def cargar_iis(carpeta: Path | None = None) -> tuple[pd.DataFrame, list]:
    carpeta = carpeta or KIT / "logs" / "iis" / "W3SVC2"
    archivos, descartados = archivos_unicos(list(carpeta.glob("*.log")))
    df = pd.concat([leer_w3c(p) for p in archivos], ignore_index=True)
    df = _a_hora_colombia(df)
    for c in ["sc-status", "sc-substatus", "sc-win32-status", "time-taken"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["es_noc"] = df["cs(User-Agent)"].str.startswith(AGENTE_NOC, na=False)
    df["fuente"] = "iis"
    return df.sort_values("ts", ignore_index=True), descartados


def cargar_httperr(carpeta: Path | None = None) -> pd.DataFrame:
    carpeta = carpeta or KIT / "logs" / "httperr"
    df = pd.concat([leer_w3c(p) for p in sorted(carpeta.glob("*.log"))], ignore_index=True)
    df = _a_hora_colombia(df)
    df["sc-status"] = pd.to_numeric(df["sc-status"], errors="coerce")
    # HTTP.sys no registra User-Agent: el sondeo del NOC se identifica por la URI
    df["cs-uri-stem"] = df["cs-uri"].str.split("?").str[0]
    df["es_noc"] = df["cs-uri-stem"].eq("/health")
    df["fuente"] = "httperr"
    return df.sort_values("ts", ignore_index=True)


def cargar_eventos(path: Path | None = None) -> pd.DataFrame:
    path = path or KIT / "eventos" / "eventos_WEB-PAGOS-01.csv"
    df = pd.read_csv(path)
    df["_linea"] = df.index + 2  # linea en el archivo (1 = encabezado)
    df["ts"] = pd.to_datetime(df["TimeCreated"])  # ya en hora local
    return df.sort_values("ts", ignore_index=True)


def cargar_perfmon(path: Path | None = None) -> pd.DataFrame:
    path = path or KIT / "metricas" / "perfmon_WEB-PAGOS-01.csv"
    df = pd.read_csv(path)
    df.columns = ["ts", "cpu_pct", "mem_disp_mb", "disco_libre_pct", "disco_libre_mb",
                  "w3wp_private_bytes", "conexiones"]
    df["_linea"] = df.index + 2
    df["ts"] = pd.to_datetime(df["ts"], format="%m/%d/%Y %H:%M:%S.%f")
    for c in df.columns.drop(["ts", "_linea"]):
        # Perfmon deja " " cuando el proceso w3wp no existe en el muestreo
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["w3wp_mb"] = df["w3wp_private_bytes"] / 2**20
    return df


def cargar_tickets(path: Path | None = None) -> pd.DataFrame:
    path = path or KIT / "tickets" / "tickets_mesa_servicio.csv"
    df = pd.read_csv(path)
    df["ts"] = pd.to_datetime(df["FechaHoraReporte"])
    return df
