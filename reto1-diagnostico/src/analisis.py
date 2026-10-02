"""Reto 1 - Diagnostico del incidente de PortalPagos (18/09/2026).

Uso:  python reto1-diagnostico/src/analisis.py
Genera tablas (CSV/MD) y graficas (PNG) en reto1-diagnostico/salidas/.
Todas las horas estan en hora de Colombia (UTC-5).
"""
from __future__ import annotations

import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import statsmodels.api as sm

sys.path.insert(0, str(Path(__file__).parent))
from carga import (cargar_eventos, cargar_httperr, cargar_iis, cargar_perfmon,  # noqa: E402
                   cargar_tickets)

SALIDAS = Path(__file__).resolve().parents[1] / "salidas"
SALIDAS.mkdir(exist_ok=True)

DESPLIEGUE = pd.Timestamp("2026-09-15 22:03:00")  # eventos linea 109
RETIRO_D = pd.Timestamp("2026-09-16 11:30:02")    # eventos linea 150
FIN_DATOS = pd.Timestamp("2026-09-20 23:55:00")

# Rutas que solo piden los escaneres automaticos (ticket T-10236): no son usuarios
RUTAS_ESCANER = {"/.env", "/wp-login.php", "/phpmyadmin/index.php", "/admin/config.php"}
UMBRAL_ERROR_PCT = 5.0      # mismo umbral de la alerta de ejemplo (alerta_ejemplo.json)
UMBRAL_LENTO_MS = 3000      # p95 por encima de 3 s = experiencia degradada (supuesto)

AZUL, ROJO, GRIS, NARANJA = "#2a78d6", "#e34948", "#52514e", "#eb6834"
plt.rcParams.update({"font.size": 9, "axes.spines.top": False, "axes.spines.right": False,
                     "axes.grid": True, "grid.color": "#e6e5e0", "grid.linewidth": 0.6,
                     "axes.edgecolor": "#bdbcb6", "figure.dpi": 130})


def md(df: pd.DataFrame) -> str:
    """Tabla markdown sin depender de 'tabulate'."""
    cols = [str(c) for c in df.columns]
    filas = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for _, r in df.iterrows():
        filas.append("| " + " | ".join(str(v) for v in r.values) + " |")
    return "\n".join(filas)


# --------------------------------------------------------------------------- datos
def preparar():
    iis, descartados = cargar_iis()
    h = cargar_httperr()
    ev = cargar_eventos()
    pm = cargar_perfmon()
    tk = cargar_tickets()

    iis["es_escaner"] = (iis["cs(User-Agent)"].str.contains("zgrab", na=False)
                         | iis["cs-uri-stem"].isin(RUTAS_ESCANER))
    h["es_escaner"] = h["cs-uri-stem"].isin(RUTAS_ESCANER) | h["sc-status"].isna()
    # IP real del cliente: X-Forwarded-For cuando existe (balanceador desde el 16/09 22:12)
    xff = iis.get("X-Forwarded-For")
    iis["ip_cliente"] = np.where(xff.notna() & (xff != "-"), xff, iis["c-ip"])

    cols = ["ts", "cs-uri-stem", "sc-status", "time-taken", "fuente", "_archivo", "_linea"]
    usuarios = pd.concat([
        iis[~iis.es_noc & ~iis.es_escaner][cols],
        h[~h.es_noc & ~h.es_escaner].assign(**{"time-taken": np.nan})[cols],
    ], ignore_index=True).sort_values("ts", ignore_index=True)
    usuarios["falla"] = usuarios["sc-status"] >= 500
    usuarios["estatico"] = usuarios["cs-uri-stem"].str.startswith("/static") | \
        usuarios["cs-uri-stem"].eq("/favicon.ico")
    return dict(iis=iis, h=h, ev=ev, pm=pm, tk=tk, usuarios=usuarios, descartados=descartados)


# --------------------------------------------------------------- calidad de datos
def primera_fila_xff(iis: pd.DataFrame) -> pd.Series:
    """Primera fila (en orden del archivo) con el esquema nuevo que trae X-Forwarded-For."""
    x = iis[iis["X-Forwarded-For"].notna()]
    return x.sort_values(["ts", "_linea"]).iloc[0]



def calidad(d) -> pd.DataFrame:
    iis, h, pm, ev = d["iis"], d["h"], d["pm"], d["ev"]
    cambio = primera_fila_xff(iis)
    blancos = pm[pm.w3wp_private_bytes.isna()]
    log_mant = (Path(__file__).resolve().parents[2] / "kit_prueba_portalpagos/scripts/mantenimiento.log")
    lineas_mant = log_mant.read_text().splitlines()
    filas = [
        ("Archivo duplicado", f"`{d['descartados'][0][0].name}` es identico (SHA-256) a "
         f"`{d['descartados'][0][1].name}`; se carga una sola vez."),
        ("Zona horaria", "IIS y HTTP.sys escriben en UTC: `u_ex260914.log` empieza a las 05:00 UTC "
         "(00:00 en Colombia) y `u_ex260921.log` solo llega a las 04:59 UTC. Se restan 5 h. "
         "Eventos y Perfmon ya estan en hora local."),
        ("Cambio de esquema W3C", f"`{cambio._archivo}` cambia de campos en la linea {cambio._linea - 1}: "
         "se agregan `cs-host` y `X-Forwarded-For`. Desde ahi `c-ip` es el balanceador 10.20.4.4 y la "
         "IP real del cliente viene en `X-Forwarded-For`."),
        ("Huecos en Perfmon", f"{len(blancos)} muestras sin valor de `Process(w3wp)\\Private Bytes` "
         f"(lineas {', '.join(map(str, blancos._linea))}). Coinciden con momentos sin proceso w3wp "
         "(reinicios y la caida). Se tratan como nulos, no como cero."),
        ("Log del mantenimiento", f"`mantenimiento.log` tiene {len(lineas_mant)} lineas 'Proceso OK' sin fecha "
         "ni detalle; el .BAT lo escribe siempre, falle o no. No sirve como evidencia."),
        ("Eventos incompletos", "La exportacion no tiene el evento del reinicio manual del pool a las 15:04 "
         "(solo consta en el ticket T-10255). Tampoco hay eventos 'stopped' del Servicio Notificaciones, "
         "solo 'running'."),
        ("Ruido", f"Sondeo del NOC (`NOC-HealthProbe`, {int(iis.es_noc.sum())} peticiones) y escaneres "
         f"(zgrab y rutas como /.env, {int(iis.es_escaner.sum())} peticiones) se excluyen del calculo "
         "de usuarios reales."),
        ("HTTP.sys", f"`httperr1.log` tiene {int((h['sc-status'] == 503).sum())} respuestas 503 AppOffline que "
         "**no aparecen en el log de IIS**: si solo se mira IIS, la caida es invisible."),
    ]
    return pd.DataFrame(filas, columns=["Tema", "Hallazgo y tratamiento"])


# ------------------------------------------------------------------- linea de tiempo
def linea_tiempo(d) -> pd.DataFrame:
    u, ev, h, tk, pm = d["usuarios"], d["ev"], d["h"], d["tk"], d["pm"]
    dia = u[(u.ts >= "2026-09-18") & (u.ts < "2026-09-19")]
    din = dia[~dia.estatico & (dia.fuente == "iis")].set_index("ts")
    p95 = din["time-taken"].resample("10min").quantile(0.95)
    base = d["usuarios"][(d["usuarios"].ts < DESPLIEGUE) & ~d["usuarios"].estatico &
                         (d["usuarios"].ts.dt.hour.between(8, 17))]["time-taken"].quantile(0.95)
    inicio_degr = p95[(p95.index.hour >= 8) & (p95 > 1.5 * base)].index.min()
    lento = p95[(p95.index.hour >= 8) & (p95 > UMBRAL_LENTO_MS)].index.min()
    oom = ev[ev.Message.str.contains("OutOfMemory") & (ev.ts.dt.date.astype(str) == "2026-09-18")]
    f500 = dia[dia.falla & (dia.ts >= oom.ts.min() - pd.Timedelta(minutes=5)) & (dia.fuente == "iis")].iloc[0]
    crash = ev[(ev.Id == 1026)]
    was = ev[ev.Id == 5002].iloc[0]
    h503 = h[(h["sc-status"] == 503) & ~h.es_noc]
    disco = ev[ev.Id == 2013].iloc[0]
    rec = dia[(dia.fuente == "iis") & (dia.ts > h503.ts.max())].iloc[0]
    alerta = pd.Timestamp("2026-09-18T19:00:00") - pd.Timedelta(hours=5)

    e = []
    def add(ts, fase, que, usuario, evidencia):
        e.append((ts, fase, que, usuario, evidencia))

    add(DESPLIEGUE, "Antecedente", "Despliegue PortalPagos v2.3.1: nuevo flujo de confirmacion, "
        "cache de sesiones de pago y log en nivel Debug", "Nada visible", "eventos linea 109")
    add(RETIRO_D, "Antecedente", "Se retira la unidad D:. Los logs pasan a C:, pero el .BAT sigue "
        "limpiando D:\\logs\\iis", "Nada visible", "eventos linea 150; mantenimiento_diario.bat")
    lb = primera_fila_xff(d["iis"])
    add(lb.ts, "Antecedente", "Aparece un balanceador/proxy delante del servidor (nuevo campo "
        "X-Forwarded-For; c-ip pasa a 10.20.4.4). No hay registro de ese cambio", "Nada visible",
        f"{lb._archivo} linea {lb._linea - 1}")
    add(pd.Timestamp("2026-09-17 16:10"), "Señal ignorada", "Ticket 'Portal de pagos lento en la tarde', "
        "cerrado con 'monitoreo en verde'", "Lentitud", "tickets T-10240")
    add(pd.Timestamp("2026-09-18 02:00:01"), "Antecedente", "iisreset nocturno: memoria de w3wp vuelve "
        "a ~300 MB", "Nada visible", "eventos linea 271")
    add(inicio_degr, "Inicio de degradacion", f"p95 de latencia supera 1,5x la linea base "
        f"({base:,.0f} ms) con memoria de w3wp en {pm.set_index('ts').w3wp_mb.asof(inicio_degr):,.0f} MB",
        "Paginas algo mas lentas", "u_ex260918.log; perfmon")
    add(lento, "Degradacion fuerte", f"p95 > {UMBRAL_LENTO_MS/1000:.0f} s", "Lentitud notoria al consultar y pagar",
        "u_ex260918.log")
    add(f500.ts, "Primer error", f"Primer 500 del incidente ({f500['cs-uri-stem']})", "Error al pagar",
        f"{f500._archivo} linea {f500._linea}")
    add(oom.ts.min(), "Primer error", "Primera OutOfMemoryException en SesionPagoCache.Agregar "
        "(/api/pagos/confirmar)", "'Ha ocurrido un error inesperado'", f"eventos linea {oom._linea.min()}")
    add(pd.Timestamp("2026-09-18 13:34"), "Reporte", "Primer ticket de usuarios (T-10252)",
        "Error al confirmar pago", "tickets T-10252")
    add(alerta, "Deteccion (hipotetica)", "Hora de la alerta de ejemplo (5xx > 5%), si hubiera existido",
        "-", "alerta_ejemplo.json (firedDateTime 19:00Z)")
    add(crash.ts.iloc[0], "Caida", "Primer crash de w3wp por OutOfMemory (se genera dump)",
        "Conexiones cortadas", f"eventos lineas {crash._linea.iloc[0]}-{crash._linea.iloc[0] + 3}")
    add(crash.ts.iloc[1], "Caida", f"Crashes en cadena: {len(crash)} entre "
        f"{crash.ts.min():%H:%M} y {crash.ts.max():%H:%M}", "Errores intermitentes",
        f"eventos lineas {', '.join(map(str, crash._linea))}")
    add(was.ts, "Caida total", "Rapid-Fail Protection deshabilita PortalPagosPool", "Service Unavailable (503)",
        f"eventos linea {was._linea}")
    add(h503.ts.min(), "Caida total", f"HTTP.sys responde 503 AppOffline a todo", "Service Unavailable",
        "httperr1.log linea 5")
    add(pd.Timestamp("2026-09-18 14:42"), "Reporte", "Ticket critico T-10255 'Portal caido'", "-", "tickets T-10255")
    add(pd.Timestamp("2026-09-18 15:04"), "Recuperacion", "Reinicio manual del pool", "-", "tickets T-10255 (sin evento)")
    add(rec.ts, "Recuperacion", "Primera respuesta de IIS despues de la caida", "Portal disponible",
        f"{rec._archivo} linea {rec._linea}")
    add(disco.ts, "Riesgo", "Aviso del sistema: disco C: casi lleno", "Nada visible (aun)", f"eventos linea {disco._linea}")
    add(pd.Timestamp("2026-09-20 09:15"), "Señal ignorada", "Revision semanal NOC: 'sin novedades', "
        "/health OK 100%", "-", "tickets T-10270")
    t = pd.DataFrame(e, columns=["hora", "fase", "que_paso", "que_vio_el_usuario", "evidencia"]).sort_values("hora")
    t.to_csv(SALIDAS / "linea_tiempo.csv", index=False)
    return t


# -------------------------------------------------------------------- disponibilidad
def disponibilidad(d):
    u = d["usuarios"]
    din = u[~u.estatico]
    dia = din.groupby(din.ts.dt.date).agg(peticiones=("falla", "size"), fallas=("falla", "sum"))
    dia["disp_peticiones_pct"] = 100 * (1 - dia.fallas / dia.peticiones)

    v = din.set_index("ts").resample("5min").agg(n=("falla", "size"), f=("falla", "sum"))
    v["err_pct"] = 100 * v.f / v.n.replace(0, np.nan)
    # Ventana no disponible: > 5 % de errores y al menos 3 fallas (evita que 1 error
    # aislado en la madrugada, con 10 peticiones, cuente como caida)
    v["caida"] = (v.err_pct > UMBRAL_ERROR_PCT) & (v.f >= 3)
    v = v[v.index <= FIN_DATOS]
    dia["min_no_disponible"] = v.groupby(v.index.date).caida.sum() * 5
    dia["disp_tiempo_pct"] = 100 * (1 - dia.min_no_disponible / (24 * 60))

    # Lo que ve el NOC: el sondeo /health cada 30 s
    iis, h = d["iis"], d["h"]
    noc_ok = iis[iis.es_noc & (iis["sc-status"] < 500)].groupby(iis.ts.dt.date).size()
    noc_fail = h[h.es_noc].groupby(h.ts.dt.date).size()
    dia["noc_sondeos_fallidos"] = noc_fail.reindex(dia.index).fillna(0).astype(int)
    dia["disp_noc_pct"] = 100 * noc_ok / (noc_ok + dia.noc_sondeos_fallidos)

    semana = pd.Series({
        "peticiones": dia.peticiones.sum(), "fallas": dia.fallas.sum(),
        "disp_peticiones_pct": 100 * (1 - dia.fallas.sum() / dia.peticiones.sum()),
        "min_no_disponible": dia.min_no_disponible.sum(),
        "disp_tiempo_pct": 100 * (1 - dia.min_no_disponible.sum() / (len(dia) * 1440)),
        "noc_sondeos_fallidos": dia.noc_sondeos_fallidos.sum(),
        "disp_noc_pct": 100 * noc_ok.sum() / (noc_ok.sum() + dia.noc_sondeos_fallidos.sum()),
    }, name="SEMANA")
    out = pd.concat([dia, semana.to_frame().T])
    out.index.name = "dia"
    out.round(3).to_csv(SALIDAS / "disponibilidad.csv")

    # /health respondia 200 mientras los usuarios fallaban?
    ventana = (iis.ts >= "2026-09-18 13:20") & (iis.ts < "2026-09-18 14:38")
    sonda = iis[iis.es_noc & ventana]
    usu = din[(din.ts >= "2026-09-18 13:20") & (din.ts < "2026-09-18 14:38")]
    salud = dict(sondeos=len(sonda), sondeos_ok=int((sonda["sc-status"] == 200).sum()),
                 sondeo_p95_ms=float(sonda["time-taken"].quantile(.95)),
                 usuarios_err_pct=float(100 * usu.falla.mean()),
                 usuarios_p95_ms=float(usu["time-taken"].quantile(.95)))
    return out, salud


# --------------------------------------------------------------- señales tempranas
def senales(d) -> pd.DataFrame:
    pm, u = d["pm"].set_index("ts"), d["usuarios"]
    din = u[~u.estatico & (u.fuente == "iis")]
    noche = din[din.ts.dt.hour.between(19, 22)]
    s = pd.DataFrame({
        "w3wp_pico_mb": pm.w3wp_mb.groupby(pm.index.date).max(),
        "p95_19a23h_ms": noche.groupby(noche.ts.dt.date)["time-taken"].quantile(.95),
        "errores_500": din[din.falla].groupby(din[din.falla].ts.dt.date).size(),
        "disco_libre_fin_dia_gb": pm.disco_libre_mb.groupby(pm.index.date).last() / 1024,
        "peticiones": din.groupby(din.ts.dt.date).size(),
    })
    s["consumo_disco_mb"] = (-pm.disco_libre_mb.resample("1D").last().diff()).set_axis(s.index)
    s["consumo_mb_por_1k_pet"] = 1000 * s.consumo_disco_mb / s.peticiones
    s.index.name = "dia"
    s = s.round(1)
    s.to_csv(SALIDAS / "senales_tempranas.csv")
    return s


# --------------------------------------------------------------------- pronosticos
def _peticiones_por_hora(u):
    din = u[~u.estatico & (u.fuente == "iis")]
    return din.set_index("ts").resample("1h").size()


def modelo_memoria(d):
    """MB de w3wp en funcion de los pagos confirmados acumulados desde el ultimo reinicio (02:00).

    Se probaron como predictor: todas las peticiones (R2 0.95, pendiente distinta el viernes),
    /api/pagos/* (R2 0.997) y /api/pagos/confirmar (R2 0.999, pendiente estable todos los dias).
    Coincide con la pila del error: SesionPagoCache.Agregar en /api/pagos/confirmar.
    """
    pm = d["pm"].set_index("ts")
    u = d["usuarios"]
    conf = u[u["cs-uri-stem"].eq("/api/pagos/confirmar")]
    req = conf.set_index("ts").resample("5min").size()
    filas = []
    for dia in pd.date_range("2026-09-16", "2026-09-20"):
        ini, fin = dia + pd.Timedelta("2h05min"), dia + pd.Timedelta("1D1h55min")
        if dia == pd.Timestamp("2026-09-18"):
            fin = pd.Timestamp("2026-09-18 14:20")  # antes del primer crash
        r = req[ini:fin].cumsum()
        m = pm.w3wp_mb[ini:fin]
        x = pd.concat([r.rename("acum"), m.rename("mb")], axis=1).dropna()
        x["dia"] = dia.date()
        filas.append(x)
    x = pd.concat(filas)
    fit = sm.OLS(x.mb, sm.add_constant(x.acum / 1000)).fit()
    umbral = float(pm.loc["2026-09-18 14:00":"2026-09-18 14:22"].w3wp_mb.max())
    b0, b1 = fit.params
    # Confirmaciones por ciclo (02:00 a 02:00) para comparar contra el limite
    ciclo = conf.ts - pd.Timedelta(hours=2)
    por_ciclo = conf.groupby(ciclo.dt.date).size()
    hasta_oom = int(len(conf[(conf.ts >= "2026-09-18 02:00") & (conf.ts < "2026-09-18 14:22")]))
    return dict(intercepto_mb=b0, mb_por_1k=b1, r2=fit.rsquared, umbral_oom_mb=umbral,
                pet_hasta_oom=1000 * (umbral - b0) / b1, datos=x,
                confirmaciones_por_ciclo=por_ciclo, confirmaciones_hasta_crash=hasta_oom)


def modelo_disco(d):
    """Consumo de disco por hora = a + b * peticiones (despues del despliegue), sin la hora de los dumps."""
    pm = d["pm"].set_index("ts")
    req = _peticiones_por_hora(d["usuarios"])
    cons = -pm.disco_libre_mb.resample("1h").last().diff()
    x = pd.concat([req.rename("req"), cons.rename("mb")], axis=1).dropna()
    x = x[(x.index >= "2026-09-16 12:00")]
    x = x[~((x.index >= "2026-09-18 14:00") & (x.index <= "2026-09-18 15:00"))]  # dumps
    fit = sm.OLS(x.mb, sm.add_constant(x.req)).fit()
    dumps_mb = float(-(pm.disco_libre_mb["2026-09-18 15:00"] - pm.disco_libre_mb["2026-09-18 14:20"])
                     - fit.params["req"] * req["2026-09-18 14:00":"2026-09-18 14:59"].sum())

    # Proyeccion desde el domingo 20/09 23:55. El ajuste es casi perfecto (datos sinteticos),
    # asi que la incertidumbre real esta en el TRAFICO, no en el coeficiente: se proyectan
    # tres escenarios de demanda con el perfil horario observado.
    hora = req.index.hour
    sel = lambda a, b: req[(req.index >= a) & (req.index < b)]  # noqa: E731
    lun_jue = sel("2026-09-14", "2026-09-18")
    perfiles = {
        "bajo (como fin de semana)": sel("2026-09-19", "2026-09-21").groupby(sel("2026-09-19", "2026-09-21").index.hour).mean(),
        "normal (promedio lun-jue)": lun_jue.groupby(lun_jue.index.hour).mean(),
        "alto (como el viernes 18/09)": sel("2026-09-18", "2026-09-19").groupby(sel("2026-09-18", "2026-09-19").index.hour).mean(),
    }
    libre0 = float(pm.disco_libre_mb.iloc[-1])
    total_mb = float((pm.disco_libre_mb / (pm.disco_libre_pct / 100)).median())
    futuro = pd.date_range(FIN_DATOS.ceil("h"), periods=24 * 10, freq="1h")
    escenarios = {}
    for nombre, perfil in perfiles.items():
        demanda = perfil.reindex(futuro.hour).to_numpy()
        consumo = fit.params["const"] + fit.params["req"] * demanda
        serie = pd.Series(libre0 - np.cumsum(consumo), index=futuro)
        escenarios[nombre] = dict(
            serie=serie,
            gb_dia=float(consumo[:24].sum() / 1024),
            bajo_5pct=serie[serie < 0.05 * total_mb].index.min(),
            lleno=serie[serie <= 0].index.min(),
        )
    return dict(fit=fit, mb_por_peticion=fit.params["req"], base_mb_h=fit.params["const"],
                r2=fit.rsquared, dumps_mb=dumps_mb, libre0=libre0, total_mb=total_mb,
                escenarios=escenarios)


def eventos_por_dia(ev) -> pd.DataFrame:
    nombres = {10016: "DCOM 10016 (warning)", 36887: "Schannel TLS alerta 46", 1309: "ASP.NET excepcion no manejada",
               1026: ".NET crash w3wp", 5002: "WAS pool deshabilitado", 2013: "Disco casi lleno",
               3201: "iisreset (stop)", 201: "Tarea mantenimiento 'OK'"}
    e = ev[ev.Id.isin(nombres)].copy()
    e["evento"] = e.Id.map(nombres)
    n = ev[ev.Message.str.contains("Servicio Notificaciones")].assign(evento="Servicio Notificaciones 'running'")
    t = pd.crosstab(pd.concat([e, n]).evento, pd.concat([e, n]).ts.dt.strftime("%d/%m"))
    t.columns.name = None
    t.index.name = "evento"
    return t


# ------------------------------------------------------------------------- graficas
def _marca(ax, ts, texto, y=0.97):
    ax.axvline(ts, color=GRIS, lw=0.8, ls="--")
    ax.text(ts, y, " " + texto, transform=ax.get_xaxis_transform(), fontsize=7.5, color=GRIS,
            va="top", ha="left")


def grafica_incidente(d):
    u, pm = d["usuarios"], d["pm"].set_index("ts")
    ini, fin = pd.Timestamp("2026-09-18 08:00"), pd.Timestamp("2026-09-18 17:00")
    din = u[~u.estatico & (u.ts >= ini) & (u.ts < fin)].set_index("ts")
    r = din.resample("5min").agg(n=("falla", "size"), f=("falla", "sum"))
    r["err"] = 100 * r.f / r.n.replace(0, np.nan)
    p95 = din[din.fuente == "iis"]["time-taken"].resample("5min").quantile(.95) / 1000

    fig, ax = plt.subplots(4, 1, figsize=(9, 8.5), sharex=True)
    ax[0].plot(r.index, r.n, color=AZUL, lw=1.6)
    ax[0].set_title("Peticiones de usuarios cada 5 min (IIS + HTTP.sys)", loc="left", fontsize=9.5)
    ax[1].plot(r.index, r.err, color=ROJO, lw=1.6)
    ax[1].axhline(UMBRAL_ERROR_PCT, color=GRIS, lw=0.8, ls=":")
    ax[1].set_title("% de peticiones con error (5xx)  ·  linea punteada = umbral 5 %", loc="left", fontsize=9.5)
    ax[2].plot(p95.index, p95, color=NARANJA, lw=1.6)
    ax[2].set_yscale("log")
    ax[2].set_title("Latencia p95 (segundos, escala log)", loc="left", fontsize=9.5)
    m = pm.w3wp_mb[ini:fin]
    ax[3].plot(m.index, m, color=AZUL, lw=1.6, marker="o", ms=2.5)
    ax[3].set_title("Memoria privada de w3wp (MB)", loc="left", fontsize=9.5)
    for a in ax:
        _marca(a, pd.Timestamp("2026-09-18 13:24"), "1a OutOfMemory")
        _marca(a, pd.Timestamp("2026-09-18 14:38"), "pool deshabilitado")
        _marca(a, pd.Timestamp("2026-09-18 15:04"), "reinicio manual", y=0.75)
    ax[3].xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
    fig.suptitle("Viernes 18/09/2026 - hora de Colombia", x=0.01, ha="left", fontsize=11, fontweight="bold")
    fig.tight_layout()
    fig.savefig(SALIDAS / "fig1_incidente_18sep.png")
    plt.close(fig)


def grafica_semana(d, mem, disco):
    pm = d["pm"].set_index("ts")
    fig, ax = plt.subplots(2, 1, figsize=(9, 6), sharex=True)
    ax[0].plot(pm.index, pm.w3wp_mb, color=AZUL, lw=1.2)
    ax[0].axhline(mem["umbral_oom_mb"], color=ROJO, lw=0.8, ls=":")
    ax[0].text(pm.index[5], mem["umbral_oom_mb"] + 30, f"nivel del OutOfMemory (~{mem['umbral_oom_mb']:,.0f} MB)",
               fontsize=7.5, color=ROJO)
    ax[0].set_title("Memoria privada de w3wp (MB): crece sin parar desde el despliegue; "
                    "el iisreset de las 02:00 la 'esconde'", loc="left", fontsize=9.5)
    esc = disco["escenarios"]
    ax[1].plot(pm.index, pm.disco_libre_mb / 1024, color=AZUL, lw=1.4, label="Medido")
    c = esc["normal (promedio lun-jue)"]["serie"]
    c = c[c > -3000]
    ax[1].plot(c.index, c / 1024, color=AZUL, lw=1.4, ls="--", label="Pronostico, trafico normal")
    lo = esc["bajo (como fin de semana)"]["serie"].reindex(c.index)
    hi = esc["alto (como el viernes 18/09)"]["serie"].reindex(c.index)
    ax[1].fill_between(c.index, lo / 1024, hi / 1024, color=AZUL, alpha=0.12, lw=0,
                       label="Rango trafico bajo / alto")
    ax[1].axhline(0, color=ROJO, lw=0.8)
    ax[1].axhline(0.05 * disco["total_mb"] / 1024, color=ROJO, lw=0.8, ls=":")
    ax[1].set_title("Espacio libre en C: (GB) y pronostico", loc="left", fontsize=9.5)
    ax[1].legend(loc="upper right", frameon=False, fontsize=8)
    for a in ax:
        _marca(a, DESPLIEGUE, "despliegue v2.3.1")
        _marca(a, pd.Timestamp("2026-09-18 14:38"), "caida", y=0.80)
    ax[1].xaxis.set_major_formatter(mdates.DateFormatter("%a %d"))
    fig.tight_layout()
    fig.savefig(SALIDAS / "fig2_semana_memoria_disco.png")
    plt.close(fig)


def grafica_fuga(mem):
    x = mem["datos"]
    fig, ax = plt.subplots(figsize=(7, 4))
    colores = [AZUL, NARANJA, ROJO, "#1baf7a", "#4a3aa7"]
    for (dia, g), col in zip(x.groupby("dia"), colores):
        ax.plot(g.acum / 1000, g.mb, ".", ms=3, color=col, label=str(dia))
    xs = np.linspace(0, mem["pet_hasta_oom"] / 1000 * 1.05, 50)
    ax.plot(xs, mem["intercepto_mb"] + mem["mb_por_1k"] * xs, color=GRIS, lw=1)
    ax.axhline(mem["umbral_oom_mb"], color=ROJO, lw=0.8, ls=":")
    ax.set_xlabel("Miles de pagos confirmados (/api/pagos/confirmar) desde el reinicio de las 02:00")
    ax.set_ylabel("Memoria privada w3wp (MB)")
    ax.set_title(f"La memoria crece {mem['mb_por_1k']/1000:.2f} MB por cada pago confirmado "
                 f"(R² = {mem['r2']:.3f})", loc="left", fontsize=9.5)
    ax.legend(frameon=False, fontsize=8)
    fig.tight_layout()
    fig.savefig(SALIDAS / "fig3_fuga_memoria.png")
    plt.close(fig)


# ---------------------------------------------------------------------- reportes
FASE_TONO = {"Antecedente": "", "Señal ignorada": "alerta", "Inicio de degradacion": "alerta",
             "Degradacion fuerte": "alerta", "Primer error": "critico", "Reporte": "",
             "Deteccion (hipotetica)": "ok", "Caida": "critico", "Caida total": "critico",
             "Recuperacion": "ok", "Riesgo": "alerta"}


def _es(numero: str) -> str:
    """'1,234.5' -> '1.234,5' (formato es-CO para textos)."""
    return numero.replace(",", "_").replace(".", ",").replace("_", ".")


DIAS_ES = ["lun", "mar", "mié", "jue", "vie", "sáb", "dom"]


def _fecha(ts, formato="%d/%m %H:%M") -> str:
    """Fecha con dia de la semana en español (strftime depende del idioma del sistema)."""
    return f"{DIAS_ES[ts.weekday()]} {ts.strftime(formato)}"


ETIQUETAS = {
    "dia": "Día", "peticiones": "Operaciones", "fallas": "Fallas",
    "disp_peticiones_pct": "Disp. por operación (%)", "min_no_disponible": "Min. no disponible",
    "disp_tiempo_pct": "Disp. por tiempo (%)", "noc_sondeos_fallidos": "Sondeos NOC fallidos",
    "disp_noc_pct": "Disp. según sondeo NOC (%)", "w3wp_pico_mb": "Memoria pico w3wp (MB)",
    "p95_19a23h_ms": "Latencia p95 19-23 h (ms)", "errores_500": "Errores 500",
    "disco_libre_fin_dia_gb": "Disco libre fin del día (GB)", "consumo_disco_mb": "Consumo disco (MB)",
    "consumo_mb_por_1k_pet": "MB de disco por 1.000 operaciones", "hora": "Hora", "fase": "Fase",
    "que_paso": "Qué pasó", "que_vio_el_usuario": "Qué vio el usuario", "evidencia": "Evidencia",
    "evento": "Evento",
}


def armar_secciones(d, t, disp, salud, s, mem, disco) -> tuple[list, list]:
    """Estructura comun para el reporte HTML y el Markdown: (kpis, secciones)."""
    fmt = lambda ts: "no ocurre en 10 dias" if pd.isna(ts) else _fecha(ts, "%d/%m %H:00")  # noqa: E731
    esc = disco["escenarios"]
    normal = esc["normal (promedio lun-jue)"]
    vie = disp.loc[pd.Timestamp("2026-09-18").date()]
    sem = disp.loc["SEMANA"]

    kpis = [
        ("Disponibilidad real viernes 18/09", _es(f"{vie.disp_peticiones_pct:.1f} %"),
         _es(f"{int(vie.fallas):,} operaciones fallidas"), "critico"),
        ("Disponibilidad real de la semana", _es(f"{sem.disp_peticiones_pct:.1f} %"),
         "por operacion de usuario", "alerta"),
        ("Lo que reporto el NOC", "100 %", _es(f"su propio sondeo /health: {sem.disp_noc_pct:.2f} %"), "neutro"),
        ("Caida total", "26 min", "14:38 a 15:04 · degradacion desde 11:30", "critico"),
        ("Fuga de memoria", _es(f"{mem['mb_por_1k'] / 1000:.2f} MB"),
         _es(f"por pago confirmado · limite ~{mem['pet_hasta_oom']:,.0f} pagos entre reinicios"), "alerta"),
        ("Disco C: lleno (trafico normal)", fmt(normal["lleno"]),
         _es(f"quedan {disco['libre0'] / 1024:.1f} GB · {normal['gb_dia']:.1f} GB/dia"), "critico"),
    ]

    tl = t.assign(hora=t.hora.map(lambda x: _fecha(x, "%d/%m %H:%M:%S"))).rename(columns=ETIQUETAS)
    dd = disp.reset_index()
    dd["dia"] = dd["dia"].map(lambda x: x if isinstance(x, str) else _fecha(pd.Timestamp(x), "%d/%m"))
    dd = dd.round(2).rename(columns=ETIQUETAS)
    cpc = (mem["confirmaciones_por_ciclo"].rename("confirmaciones")
           .rename_axis("ciclo que inicia a las 02:00 del").reset_index())
    cpc["% del limite"] = (100 * cpc.confirmaciones / mem["pet_hasta_oom"]).round(0)
    cpc.iloc[:, 0] = cpc.iloc[:, 0].map(lambda x: _fecha(pd.Timestamp(x), "%d/%m"))
    s2 = s.reset_index()
    s2["dia"] = s2["dia"].map(lambda x: _fecha(pd.Timestamp(x), "%d/%m"))
    s2 = s2.rename(columns=ETIQUETAS)
    pron = pd.DataFrame([(k, round(v["gb_dia"], 1), fmt(v["bajo_5pct"]), fmt(v["lleno"])) for k, v in esc.items()],
                        columns=["escenario de trafico", "GB/dia", "libre < 5 %", "disco lleno"])

    nota_salud = (f"Mientras los usuarios fallaban (18/09 13:20-14:38): **{salud['usuarios_err_pct']:.1f} %** de "
                  f"errores y p95 de **{salud['usuarios_p95_ms'] / 1000:.1f} s**; el sondeo /health respondio 200 en "
                  f"**{salud['sondeos_ok']} de {salud['sondeos']}** intentos (p95 {salud['sondeo_p95_ms']:.0f} ms).")
    texto_mem = (f"**{mem['mb_por_1k'] / 1000:.3f} MB por cada pago confirmado** (R² {mem['r2']:.3f}), partiendo de "
                 f"{mem['intercepto_mb']:.0f} MB tras el reinicio. El OutOfMemory aparecio con "
                 f"~{mem['umbral_oom_mb']:,.0f} MB: se alcanza con ~{mem['pet_hasta_oom']:,.0f} confirmaciones en un "
                 f"mismo ciclo entre reinicios (observado el 18/09: {mem['confirmaciones_hasta_crash']:,} "
                 "confirmaciones entre las 02:00 y el primer crash).")
    texto_disco = (f"Consumo = {disco['base_mb_h']:.0f} MB/h + **{disco['mb_por_peticion']:.3f} MB por peticion** "
                   f"(R² {disco['r2']:.2f}). Los dumps del 18/09 ocuparon ~{disco['dumps_mb']:,.0f} MB. "
                   f"Libre al cierre: {disco['libre0'] / 1024:.1f} GB de {disco['total_mb'] / 1024:.0f} GB.")

    secciones = [
        dict(id="calidad", titulo="1. Calidad de los datos",
             texto=["Los archivos llegan sin depurar. Estas decisiones de limpieza cambian las conclusiones."],
             tablas=[dict(df=calidad(d))]),
        dict(id="linea", titulo="2. Linea de tiempo",
             texto=["Hora de Colombia. Cada fila cita el archivo y la linea que la respalda."],
             tablas=[dict(df=tl, filtro=True, chips={"Fase": lambda v: FASE_TONO.get(v, "")})],
             figuras=[SALIDAS / "fig1_incidente_18sep.png"]),
        dict(id="disp", titulo="3. Disponibilidad real vs. NOC",
             texto=["Usuarios reales: sin archivos estaticos, sin el sondeo del NOC y sin escaneres. "
                    "`disp_tiempo_pct` cuenta ventanas de 5 min con mas de 5 % de errores y al menos 3 fallas."],
             tablas=[dict(df=dd, nota=[nota_salud],
                          resaltar=lambda f: "total" if f["Día"] == "SEMANA"
                          else ("critico" if f["Disp. por operación (%)"] < 99 else ""))]),
        dict(id="senales", titulo="4. Señales tempranas",
             texto=["Desde el miercoles 16/09 la memoria pico, la latencia nocturna y el consumo de disco "
                    "se multiplican frente a lunes y martes."],
             tablas=[dict(df=s2, resaltar=lambda f: "critico" if f["Día"].startswith("vie 18")
                          else ("alerta" if f["Memoria pico w3wp (MB)"] > 900 else ""))],
             figuras=[SALIDAS / "fig2_semana_memoria_disco.png"]),
        dict(id="memoria", titulo="5. Pronostico: fuga de memoria", texto=[texto_mem],
             tablas=[dict(df=cpc, resaltar=lambda f: "critico" if f["% del limite"] >= 100
                          else ("alerta" if f["% del limite"] >= 75 else ""))],
             figuras=[SALIDAS / "fig3_fuga_memoria.png"]),
        dict(id="disco", titulo="6. Pronostico: disco C:",
             texto=[texto_disco,
                    "Cada crash adicional de w3wp deja un dump de ~1,4 GB en C:\\CrashDumps y adelanta el llenado."],
             tablas=[dict(df=pron, resaltar=lambda f: "critico" if "normal" in f["escenario de trafico"] else "")]),
        dict(id="eventos", titulo="7. Eventos de Windows por dia",
             texto=["Separa ruido de señal: DCOM 10016 aparece igual toda la semana; los eventos criticos solo el 18/09."],
             tablas=[dict(df=eventos_por_dia(d["ev"]).reset_index().rename(columns=ETIQUETAS),
                          resaltar=lambda f: "critico" if f["Evento"] in
                          {".NET crash w3wp", "WAS pool deshabilitado", "ASP.NET excepcion no manejada"} else "")]),
    ]
    return kpis, secciones


def escribir_markdown(kpis, secciones) -> Path:
    r = ["# Reto 1 - Resultados generados por `analisis.py`\n",
         "Todas las horas en hora de Colombia (UTC-5). Archivo generado: no editar a mano. "
         "Version visual: `reporte.html`.\n",
         md(pd.DataFrame([(lab, v, det) for lab, v, det, _ in kpis], columns=["Indicador", "Valor", "Detalle"])), ""]
    for s in secciones:
        r.append(f"## {s['titulo']}\n")
        r += [p + "\n" for p in s.get("texto", [])]
        for t in s.get("tablas", []):
            r += [md(t["df"]), ""] + [p + "\n" for p in t.get("nota", [])]
        r += [f"![{f.stem}]({f.name})\n" for f in s.get("figuras", [])]
    destino = SALIDAS / "resultados.md"
    destino.write_text("\n".join(r), encoding="utf-8")
    return destino


# ---------------------------------------------------------------------------- main
def main(argv=None):
    import argparse
    import webbrowser

    from reporte_html import generar

    ap = argparse.ArgumentParser(description="Reto 1: diagnostico del incidente de PortalPagos")
    ap.add_argument("--no-abrir", action="store_true", help="no abrir el reporte en el navegador")
    args = ap.parse_args(argv)

    print("Cargando y limpiando datos del kit...")
    d = preparar()
    print("Analizando y generando graficas...")
    t = linea_tiempo(d)
    disp, salud = disponibilidad(d)
    s = senales(d)
    mem = modelo_memoria(d)
    disco = modelo_disco(d)
    grafica_incidente(d)
    grafica_semana(d, mem, disco)
    grafica_fuga(mem)

    kpis, secciones = armar_secciones(d, t, disp, salud, s, mem, disco)
    md_path = escribir_markdown(kpis, secciones)
    html_path = generar(SALIDAS / "reporte.html", "PortalPagos · Diagnostico del incidente del 18/09/2026",
                        "Andina Financiera (caso ficticio) · semana del 14 al 20 de septiembre · hora de Colombia",
                        kpis, secciones)

    print("\nResumen")
    for etiqueta, valor, detalle, _ in kpis:
        print(f"  - {etiqueta}: {valor} ({detalle})")
    print(f"\nReporte visual: {html_path}\nMarkdown:       {md_path}")
    if not args.no_abrir:
        webbrowser.open(html_path.as_uri())


if __name__ == "__main__":
    main()


