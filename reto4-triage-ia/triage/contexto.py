"""Contexto del incidente: lo que el modelo puede ver y citar.

Cada elemento tiene un id estable (ALERTA-1, EV-L304, IIS-1355, ...) y un texto corto.
El modelo solo puede afirmar cosas citando esos ids y copiando fragmentos textuales,
y el validador comprueba ambas cosas. Por eso el contexto se resume (bloques de 5 min,
eventos repetidos agrupados) en vez de pasar miles de lineas crudas.

Fuentes:
- FuenteKit: lee los archivos del kit (Retos 1 y 4, sin nube).
- FuenteLogAnalytics: misma salida, consultando Log Analytics con KQL (base para el Reto 3).
"""
from __future__ import annotations

import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Protocol

import pandas as pd

RAIZ = Path(__file__).resolve().parents[2]
OFFSET_CO = pd.Timedelta(hours=-5)
RUTAS_ESCANER = {"/.env", "/wp-login.php", "/phpmyadmin/index.php", "/admin/config.php"}


@dataclass(frozen=True)
class Elemento:
    id: str
    fuente: str
    ts: str          # hora de Colombia, ISO
    texto: str

    def como_linea(self) -> str:
        return f"[{self.id}] ({self.fuente}, {self.ts}) {self.texto}"


@dataclass
class Alerta:
    id: str
    regla: str
    severidad: str
    descripcion: str
    disparada_utc: pd.Timestamp
    valor: float | None
    umbral: str | None
    consulta: str | None
    objetivos: list[str]

    @property
    def disparada_local(self) -> pd.Timestamp:
        return self.disparada_utc + OFFSET_CO

    @classmethod
    def desde_esquema_comun(cls, d: dict) -> "Alerta":
        """Esquema comun de alertas de Azure Monitor (azureMonitorCommonAlertSchema)."""
        if d.get("schemaId") != "azureMonitorCommonAlertSchema":
            raise ValueError("La alerta no usa el esquema comun de Azure Monitor")
        e = d["data"]["essentials"]
        cond = (d["data"].get("alertContext") or {}).get("condition") or {}
        crit = (cond.get("allOf") or [{}])[0]
        return cls(
            id=e["alertId"].rsplit("/", 1)[-1],
            regla=e.get("alertRule", ""),
            severidad=e.get("severity", "Sev3"),
            descripcion=e.get("description", ""),
            disparada_utc=pd.Timestamp(e["firedDateTime"]).tz_convert(None),
            valor=crit.get("metricValue"),
            umbral=f'{crit.get("operator", "")} {crit.get("threshold", "")}'.strip() or None,
            consulta=crit.get("searchQuery"),
            objetivos=[t.rsplit("/", 1)[-1] for t in e.get("alertTargetIDs", [])],
        )

    def elemento(self) -> Elemento:
        partes = [f"Regla {self.regla} ({self.severidad}) disparada: {self.descripcion}."]
        if self.valor is not None:
            partes.append(f"Valor medido {self.valor} (condicion {self.umbral}).")
        if self.objetivos:
            partes.append(f"Recurso: {', '.join(self.objetivos)}.")
        return Elemento("ALERTA-1", "alerta", self.disparada_local.isoformat(), " ".join(partes))


class FuenteContexto(Protocol):
    def obtener(self, alerta: Alerta, desde: pd.Timestamp, hasta: pd.Timestamp) -> list[Elemento]: ...


def _hhmm(ts: pd.Timestamp) -> str:
    return ts.strftime("%H%M")


def _recortar(texto: str, n: int = 240) -> str:
    texto = " ".join(str(texto).split())
    return texto if len(texto) <= n else texto[: n - 1] + "…"


# ----------------------------------------------------------------------------- kit
class FuenteKit:
    """Contexto desde los archivos del kit, reutilizando la carga del Reto 1."""

    def __init__(self, fuentes: set[str] | None = None, dias_cambios: int = 7):
        sys.path.insert(0, str(RAIZ / "reto1-diagnostico" / "src"))
        import carga  # noqa: PLC0415  (reutiliza la limpieza ya probada del Reto 1)

        self._c = carga
        self.fuentes = fuentes or {"eventos", "iis", "httperr", "perfmon", "cambios"}
        self.dias_cambios = dias_cambios
        self._cache: dict = {}

    def _df(self, nombre):
        if nombre not in self._cache:
            self._cache[nombre] = {
                "iis": lambda: self._c.cargar_iis()[0],
                "httperr": self._c.cargar_httperr,
                "eventos": self._c.cargar_eventos,
                "perfmon": self._c.cargar_perfmon,
            }[nombre]().rename(columns={"_linea": "linea"})  # itertuples oculta columnas con "_"
        return self._cache[nombre]

    def obtener(self, alerta, desde, hasta):
        el: list[Elemento] = []
        if "cambios" in self.fuentes:
            el += self._cambios(desde)
        if "eventos" in self.fuentes:
            el += self._eventos(desde, hasta)
        if "iis" in self.fuentes:
            el += self._iis(desde, hasta)
        if "httperr" in self.fuentes:
            el += self._httperr(desde, hasta)
        if "perfmon" in self.fuentes:
            el += self._perfmon(desde, hasta)
        return el

    def _cambios(self, desde):
        ev = self._df("eventos")
        c = ev[(ev.ProviderName == "AndinaDeploy") & (ev.ts >= desde - pd.Timedelta(days=self.dias_cambios)) & (ev.ts < desde)]
        return [Elemento(f"EV-L{r.linea}", "cambios", r.ts.isoformat(), _recortar(f"{r.ProviderName} {r.Id}: {r.Message}", 300))
                for r in c.itertuples()]

    def _eventos(self, desde, hasta):
        ev = self._df("eventos")
        w = ev[(ev.ts >= desde) & (ev.ts <= hasta) & (ev.ProviderName != "AndinaDeploy")].copy()
        if w.empty:
            return []
        # Agrupa eventos repetidos (p.ej. 29 OutOfMemoryException iguales) en un solo elemento citable
        w["clave"] = w.ProviderName + "|" + w.Id.astype(str) + "|" + w.Message.str[:160]
        out = []
        for _, g in w.groupby("clave", sort=False):
            r = g.iloc[0]
            veces = f" (se repite {len(g)} veces entre {g.ts.min():%H:%M:%S} y {g.ts.max():%H:%M:%S})" if len(g) > 1 else ""
            out.append(Elemento(f"EV-L{r.linea}", "eventos", r.ts.isoformat(),
                                _recortar(f"{r.LogName}/{r.ProviderName} {r.Id} {r.LevelDisplayName}: {r.Message}", 420) + veces))
        return sorted(out, key=lambda e: e.ts)

    def _iis(self, desde, hasta):
        iis = self._df("iis")
        u = iis[(iis.ts >= desde) & (iis.ts <= hasta) & ~iis.es_noc &
                ~iis["cs(User-Agent)"].str.contains("zgrab", na=False) & ~iis["cs-uri-stem"].isin(RUTAS_ESCANER)]
        u = u[~u["cs-uri-stem"].str.startswith("/static")]
        out = []
        for ini, g in u.groupby(u.ts.dt.floor("5min")):
            err = g[g["sc-status"] >= 500]
            rutas = ", ".join(f"{k} ({v})" for k, v in err["cs-uri-stem"].value_counts().head(3).items())
            txt = (f"{ini:%H:%M}-{ini + pd.Timedelta(minutes=5):%H:%M}: {len(g)} peticiones de usuarios, "
                   f"{len(err)} con error 5xx ({100 * len(err) / len(g):.0f} %), p95 {g['time-taken'].quantile(.95) / 1000:.1f} s")
            out.append(Elemento(f"IIS-{_hhmm(ini)}", "iis", ini.isoformat(), txt + (f"; errores en {rutas}" if rutas else "")))
        noc = iis[(iis.ts >= desde) & (iis.ts <= hasta) & iis.es_noc]
        if len(noc):
            ok = int((noc["sc-status"] == 200).sum())
            out.append(Elemento("IIS-NOC", "iis", desde.isoformat(),
                                f"Sondeo /health del NOC en la ventana: {ok} de {len(noc)} respuestas 200, "
                                f"p95 {noc['time-taken'].quantile(.95):.0f} ms"))
        return out

    def _httperr(self, desde, hasta):
        h = self._df("httperr")
        w = h[(h.ts >= desde) & (h.ts <= hasta) & h["sc-status"].notna()]
        out = []
        for ini, g in w.groupby(w.ts.dt.floor("5min")):
            razones = ", ".join(f"{k} {v}" for k, v in (g["sc-status"].astype(int).astype(str) + " " +
                                                         g["s-reason"]).value_counts().items())
            out.append(Elemento(f"HTTPERR-{_hhmm(ini)}", "httperr", ini.isoformat(),
                                f"{ini:%H:%M}-{ini + pd.Timedelta(minutes=5):%H:%M}: HTTP.sys rechazo {len(g)} peticiones "
                                f"antes de llegar a IIS: {razones} (cola {g['s-queuename'].iloc[0]})"))
        return out

    def _perfmon(self, desde, hasta):
        p = self._df("perfmon")
        w = p[(p.ts >= desde) & (p.ts <= hasta)]
        out = []
        for r in w.itertuples():
            w3 = "sin proceso w3wp" if pd.isna(r.w3wp_mb) else f"w3wp memoria privada {r.w3wp_mb:.0f} MB"
            out.append(Elemento(f"PERF-{_hhmm(r.ts)}", "perfmon", r.ts.isoformat(),
                                f"{r.ts:%H:%M} CPU {r.cpu_pct:.0f} %, memoria disponible {r.mem_disp_mb:.0f} MB, "
                                f"disco C: libre {r.disco_libre_mb / 1024:.1f} GB ({r.disco_libre_pct:.0f} %), {w3}, "
                                f"conexiones {r.conexiones:.0f}"))
        return out


# ----------------------------------------------------------------- Log Analytics
class FuenteLogAnalytics:
    """Misma salida que FuenteKit, pero consultando Log Analytics (Reto 3).

    Requiere `azure-identity` y `azure-monitor-query`, y una identidad con el rol
    "Log Analytics Reader" sobre el workspace (identidad administrada en la Function).
    Pendiente de validar contra el workspace real del Reto 3.
    """

    KQL = {
        "eventos": """Event
| where TimeGenerated between (datetime({desde}) .. datetime({hasta}))
| summarize veces=count(), primero=min(TimeGenerated), ultimo=max(TimeGenerated) by Source, EventID, EventLevelName, Mensaje=substring(RenderedDescription, 0, 160)
| order by primero asc | take 30""",
        "iis": """W3CIISLog
| where TimeGenerated between (datetime({desde}) .. datetime({hasta}))
| where csUserAgent !startswith "NOC-HealthProbe" and csUriStem !startswith "/static"
| summarize peticiones=count(), err5xx=countif(scStatus >= 500), p95=percentile(TimeTaken, 95) by bin(TimeGenerated, 5m)
| order by TimeGenerated asc""",
        "perfmon": """Perf
| where TimeGenerated between (datetime({desde}) .. datetime({hasta}))
| where CounterName in ("% Processor Time", "Available MBytes", "% Free Space", "Private Bytes")
| summarize valor=avg(CounterValue) by bin(TimeGenerated, 5m), CounterName
| order by TimeGenerated asc""",
    }

    def __init__(self, workspace_id: str, credencial=None):
        from azure.identity import DefaultAzureCredential  # noqa: PLC0415
        from azure.monitor.query import LogsQueryClient  # noqa: PLC0415

        self.workspace_id = workspace_id
        self.cliente = LogsQueryClient(credencial or DefaultAzureCredential())

    def _consulta(self, nombre, desde_utc, hasta_utc):
        kql = self.KQL[nombre].format(desde=desde_utc.isoformat(), hasta=hasta_utc.isoformat())
        r = self.cliente.query_workspace(self.workspace_id, kql, timespan=None)
        t = r.tables[0]
        return pd.DataFrame(t.rows, columns=t.columns)

    def obtener(self, alerta, desde, hasta):
        d_utc, h_utc = desde - OFFSET_CO, hasta - OFFSET_CO
        el = []
        for r in self._consulta("eventos", d_utc, h_utc).itertuples():
            t = pd.Timestamp(r.primero).tz_convert(None) + OFFSET_CO
            veces = f" (se repite {r.veces} veces)" if r.veces > 1 else ""
            el.append(Elemento(f"EV-{r.Source[:12]}-{r.EventID}-{t:%H%M%S}", "eventos", t.isoformat(),
                               _recortar(f"{r.Source} {r.EventID} {r.EventLevelName}: {r.Mensaje}") + veces))
        for r in self._consulta("iis", d_utc, h_utc).itertuples():
            t = pd.Timestamp(r.TimeGenerated).tz_convert(None) + OFFSET_CO
            pct = 100 * r.err5xx / r.peticiones if r.peticiones else 0
            el.append(Elemento(f"IIS-{_hhmm(t)}", "iis", t.isoformat(),
                               f"{t:%H:%M}: {r.peticiones} peticiones, {r.err5xx} con error 5xx ({pct:.0f} %), p95 {r.p95 / 1000:.1f} s"))
        perf = self._consulta("perfmon", d_utc, h_utc)
        for ts, g in perf.groupby("TimeGenerated"):
            t = pd.Timestamp(ts).tz_convert(None) + OFFSET_CO
            v = dict(zip(g.CounterName, g.valor))
            el.append(Elemento(f"PERF-{_hhmm(t)}", "perfmon", t.isoformat(),
                               ", ".join(f"{k} {val:.0f}" for k, val in v.items())))
        return el


def construir_contexto(alerta: Alerta, fuente: FuenteContexto, minutos_antes: int = 30,
                       minutos_despues: int = 5) -> list[Elemento]:
    desde = alerta.disparada_local - pd.Timedelta(minutes=minutos_antes)
    hasta = alerta.disparada_local + pd.Timedelta(minutes=minutos_despues)
    return [alerta.elemento()] + fuente.obtener(alerta, desde, hasta)


def a_dict(elementos: list[Elemento]) -> list[dict]:
    return [asdict(e) for e in elementos]
