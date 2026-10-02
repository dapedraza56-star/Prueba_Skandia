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

# Paleta corporativa Skandia (tomada del CSS publico de skandia.co): verdes de la marca,
# gris de texto y rojo de error. El verde #00C83C es la marca; para lineas se usan tonos
# mas oscuros para que contrasten sobre fondo blanco.
AZUL, ROJO, GRIS, NARANJA = "#009047", "#E12B1C", "#3F3F3F", "#007444"
VERDE_MARCA = "#00C83C"
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
    colores = ["#5FED73", VERDE_MARCA, ROJO, "#007444", "#006042"]
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
URGENCIA_TONO = {"Crítica": "critico", "Alta": "alerta", "Media": "", "Baja": "ok"}

# Momentos que pide el enunciado: inicio de la degradacion, primer error, caida y recuperacion
FASES_CLAVE = ["Antecedente", "Señal ignorada", "Inicio de degradacion", "Degradacion fuerte",
               "Primer error", "Caida", "Caida total", "Recuperacion"]


def _es(numero: str) -> str:
    """'1,234.5' -> '1.234,5' (formato es-CO para textos)."""
    return numero.replace(",", "_").replace(".", ",").replace("_", ".")


DIAS_ES = ["lun", "mar", "mié", "jue", "vie", "sáb", "dom"]


def _fecha(ts, formato="%d/%m %H:%M") -> str:
    """Fecha con dia de la semana en español (strftime depende del idioma del sistema)."""
    return f"{DIAS_ES[ts.weekday()]} {ts.strftime(formato)}"


ACENTOS = {"confirmacion": "confirmación", "cache ": "caché ", "Paginas": "Páginas", " mas ": " más ",
           "Caida": "Caída", "Recuperacion": "Recuperación", "degradacion": "degradación",
           "Degradacion": "Degradación", "lineas": "líneas", "linea": "línea", "Revision": "Revisión"}


def _acentos(df: pd.DataFrame) -> pd.DataFrame:
    """Los textos del codigo van sin tildes (compatibilidad de consola); en el reporte se corrigen."""
    def fix(v):
        if not isinstance(v, str):
            return v
        for a, b in ACENTOS.items():
            v = v.replace(a, b)
        return v
    return df.map(fix)


def armar_secciones(d, t, disp, salud, s, mem, disco) -> tuple[list, list]:
    """Estructura comun para el reporte HTML y el Markdown: (kpis, secciones).

    Las secciones siguen las 5 preguntas del Reto 1. El detalle tecnico va en anexos.
    """
    fmt = lambda ts: "no ocurre en 10 dias" if pd.isna(ts) else _fecha(ts, "%d/%m %H:00")  # noqa: E731
    esc = disco["escenarios"]
    normal = esc["normal (promedio lun-jue)"]
    vie = disp.loc[pd.Timestamp("2026-09-18").date()]
    sem = disp.loc["SEMANA"]
    pm = d["pm"].set_index("ts")
    cpc = mem["confirmaciones_por_ciclo"]
    pct_lim = lambda dia: 100 * cpc.get(pd.Timestamp(dia).date(), 0) / mem["pet_hasta_oom"]  # noqa: E731
    cruce_900 = pm.w3wp_mb[pm.w3wp_mb > 900].index.min()

    kpis = [
        ("Disponibilidad real · viernes 18/09", _es(f"{vie.disp_peticiones_pct:.1f} %"),
         _es(f"{int(vie.fallas):,} operaciones fallidas"), "critico"),
        ("Disponibilidad real · semana", _es(f"{sem.disp_peticiones_pct:.1f} %"),
         "el NOC reportó 100 %", "alerta"),
        ("Portal caído", "26 min", "14:38 a 15:04 · con errores desde 13:23", "critico"),
        ("Disco C: lleno si no se actúa", fmt(normal["lleno"]),
         _es(f"quedan {disco['libre0'] / 1024:.1f} GB · se consumen {normal['gb_dia']:.1f} GB/día"), "critico"),
    ]

    # 1. Linea de tiempo: solo los momentos que pide el enunciado
    tl = t[t.fase.isin(FASES_CLAVE)].copy()
    tl = tl[~((tl.fase == "Recuperacion") & tl.que_paso.str.startswith("Primera respuesta"))]
    tl = tl[["hora", "fase", "que_paso", "que_vio_el_usuario", "evidencia"]]
    tl["hora"] = tl.hora.map(lambda x: _fecha(x, "%d/%m %H:%M"))
    tl.columns = ["Hora", "Fase", "Qué pasó", "Qué vio el usuario", "Evidencia"]
    tl = _acentos(tl)
    # mismas fases que FASE_TONO, pero con la ortografia que se muestra en el reporte
    tono_fase = dict(zip(_acentos(pd.DataFrame({"f": list(FASE_TONO)})).f, FASE_TONO.values()))

    # 2. Causa raiz: hechos vs hipotesis
    hechos = pd.DataFrame([
        ("Todos los errores del viernes son OutOfMemoryException en SesionPagoCache.Agregar (confirmar pago)",
         "eventos líneas 304-346 (40) y 347-368 (5 crashes)"),
        (f"La memoria del portal crece {_es(f'{mem['mb_por_1k'] / 1000:.2f}')} MB por cada pago confirmado "
         f"desde la v2.3.1 (R² {_es(f'{mem['r2']:.3f}')}); antes era estable en ~310 MB",
         "Perfmon Private Bytes vs. log IIS · figura 3"),
        (_es(f"El límite se alcanza con ~{mem['pet_hasta_oom']:,.0f} pagos sin reinicio; el viernes cayó con "
             f"{mem['confirmaciones_hasta_crash']:,}"), "modelo de memoria · log IIS"),
        ("El viernes (fin de plazo) hubo 2,3 veces los pagos de un día normal", "log IIS /api/pagos/confirmar"),
        ("Tras 5 crashes en 16 min, Windows deshabilitó el pool y todo respondió 503 hasta el reinicio manual",
         "eventos línea 366 · httperr1.log líneas 5-1545"),
        ("El reinicio nocturno de IIS (02:00) devolvía la memoria a 300 MB y ocultaba la fuga",
         "eventos 3201/3202 diarios · figura 2"),
        ("DCOM 10016 aparece igual toda la semana: no tiene relación con la caída (ticket T-10261)",
         "anexo B · eventos por día"),
    ], columns=["Hecho", "Evidencia"])
    hipotesis = pd.DataFrame([
        ("La caché guarda cada sesión de pago y nunca la expulsa (sin vencimiento ni tamaño máximo)",
         "Revisar código de SesionPagoCache v2.3.1 o un dump de C:\\CrashDumps"),
        ("El proceso falla con ~1,5 GB aunque hay 4,7 GB libres: pool en 32 bits o con límite de memoria",
         "Revisar applicationHost.config (enable32BitAppOnWin64, privateMemory)"),
        ("El disco se consume por el log en nivel Debug activado en la v2.3.1",
         "Revisar tamaño de los logs de la aplicación en C:"),
    ], columns=["Hipótesis", "Cómo confirmarla"])
    factores = [
        "**Reinicio nocturno que oculta problemas:** la fuga solo podía estallar en un día de muchos pagos.",
        "**Despliegue sin verificación posterior:** nadie comparó memoria ni tiempos antes y después de la v2.3.1.",
        "**Monitoreo de infraestructura, no de cliente:** ping y /health dicen que el servidor está prendido, "
        "no que se pueda pagar.",
        "**Señales sin conectar:** el ticket de lentitud del jueves se cerró con «monitoreo en verde».",
    ]

    # 3. Disponibilidad real vs NOC
    dd = disp.reset_index()
    dd = pd.DataFrame({
        "Día": dd["dia"].map(lambda x: x if isinstance(x, str) else _fecha(pd.Timestamp(x), "%d/%m")).replace(
            {"SEMANA": "Semana"}),
        "Operaciones": dd.peticiones.astype(int), "Fallidas": dd.fallas.astype(int),
        "Disponibilidad real (%)": dd.disp_peticiones_pct.round(2),
        "Según sondeo del NOC (%)": dd.disp_noc_pct.round(2),
        "Reportado por el NOC (%)": 100,
    })

    # 4. Señales tempranas
    sen = pd.DataFrame({
        "Día": [_fecha(pd.Timestamp(x), "%d/%m") for x in s.index],
        "Memoria pico (MB)": s.w3wp_pico_mb.round(0).astype(int).to_numpy(),
        "Pagos vs. límite de memoria (%)": [round(pct_lim(x)) for x in s.index],
        "Latencia p95 19-23 h (s)": (s.p95_19a23h_ms / 1000).round(1).to_numpy(),
        "Disco consumido (GB)": (s.consumo_disco_mb / 1024).round(1).to_numpy(),
    })

    # 5. Otros riesgos
    riesgos = pd.DataFrame([
        ("Crítica", "Disco C: se llena",
         _es(f"{disco['mb_por_peticion']:.2f} MB por operación desde la v2.3.1 y el .BAT ya no limpia (apunta a D:). "
             f"Lleno el {fmt(normal['lleno'])} con tráfico normal; {fmt(esc['alto (como el viernes 18/09)']['lleno'])} "
             f"con tráfico alto")),
        ("Alta", "La caída se repite",
         _es(f"Cualquier día con más de ~{mem['pet_hasta_oom']:,.0f} pagos entre reinicios. Un día normal ya está "
             "al 68 % del límite")),
        ("Alta", "Script de mantenimiento inseguro",
         "Contraseña en texto plano, iisreset diario innecesario y siempre reporta «OK» aunque falle"),
        ("Media", "Cambio no registrado", "Aparece un balanceador delante del servidor el 16/09 (cambia el log)"),
        ("Media", "Servicio Notificaciones inestable", "Arranca 3-8 veces por día sin registro de detención"),
        ("Baja", "Escaneos de internet", "~250 peticiones/día a /.env, /wp-login.php; hoy sin impacto"),
    ], columns=["Urgencia", "Riesgo", "Detalle y pronóstico"])
    pron = pd.DataFrame([(k.split(" (")[0].capitalize(), k.split(" (")[1].rstrip(")"), round(v["gb_dia"], 1),
                          fmt(v["bajo_5pct"]), fmt(v["lleno"])) for k, v in esc.items()],
                        columns=["Tráfico", "Supuesto", "GB por día", "Libre < 5 %", "Disco lleno"])

    secciones = [
        dict(id="linea", titulo="1. Línea de tiempo del 18/09",
             texto=["Hora de Colombia. Cuándo empezó la degradación, el primer error, la caída y la recuperación, "
                    "y qué vio el usuario en cada momento."],
             tablas=[dict(df=tl, chips={"Fase": lambda v: tono_fase.get(v, "")})],
             figuras=[SALIDAS / "fig1_incidente_18sep.png"]),
        dict(id="causa", titulo="2. Causa raíz y factores contribuyentes",
             texto=["**Causa raíz:** una fuga de memoria introducida en la versión 2.3.1 (15/09 22:03). Cada pago "
                    "confirmado deja memoria que nunca se libera; el viernes, con 2,3 veces más pagos, el proceso se "
                    "quedó sin memoria a mitad de la tarde."],
             tablas=[dict(df=hechos, titulo="Hechos (con evidencia)"),
                     dict(df=hipotesis, titulo="Hipótesis (por confirmar)")],
             lista=factores, lista_titulo="Factores que contribuyeron",
             figuras=[SALIDAS / "fig3_fuga_memoria.png"]),
        dict(id="disp", titulo="3. Disponibilidad real vs. lo que reporta el NOC",
             texto=["Disponibilidad real = operaciones de clientes sin error (sin archivos estáticos, sin el sondeo del "
                    "NOC y sin escáneres). Incluye los 503 de la caída, que solo quedaron en el log de HTTP.sys."],
             tablas=[dict(df=dd, resaltar=lambda f: "total" if f["Día"] == "Semana"
                          else ("critico" if f["Disponibilidad real (%)"] < 99 else ""),
                          nota=[f"**¿Por qué no coincide?** El NOC solo mide ping y /health. Mientras los clientes "
                                f"tenían {_es(f'{salud['usuarios_err_pct']:.0f}')} % de errores y esperas de "
                                f"{_es(f'{salud['usuarios_p95_ms'] / 1000:.0f}')} s, /health respondió OK en "
                                f"{salud['sondeos_ok']} de {salud['sondeos']} intentos: verifica que el servidor "
                                "responde, no que se pueda pagar. Solo falló en los 26 min de caída total."])]),
        dict(id="senales", titulo="4. Señales tempranas: ¿se podía ver venir?",
             texto=[f"**Sí, desde el {_fecha(cruce_900, '%d/%m a las %H:%M')}** (unas 46 horas antes): la memoria "
                    "del portal superó 900 MB por primera vez (antes del despliegue nunca pasaba de 320 MB). "
                    "El jueves los pagos ya llegaban al 78 % del límite y la latencia nocturna se triplicó.",
                    "El disco del lunes y martes casi no baja porque el script todavía liberaba espacio cada noche; "
                    "desde el 16/09 ya no (apunta a D:, que se retiró)."],
             tablas=[dict(df=sen, resaltar=lambda f: "critico" if f["Día"].startswith("vie 18")
                          else ("alerta" if f["Memoria pico (MB)"] > 900 else ""))],
             figuras=[SALIDAS / "fig2_semana_memoria_disco.png"]),
        dict(id="riesgos", titulo="5. Otros riesgos y pronóstico",
             tablas=[dict(df=riesgos, chips={"Urgencia": lambda v: URGENCIA_TONO.get(v, "")}),
                     dict(df=pron, titulo="Pronóstico del disco C: (si no se hace nada)",
                          resaltar=lambda f: "critico" if f["Tráfico"] == "Normal" else "",
                          nota=[_es(f"Método: regresión del consumo horario de disco contra las operaciones "
                                    f"(R² {disco['r2']:.2f}, {disco['mb_por_peticion']:.2f} MB por operación), "
                                    "proyectada con el perfil horario observado de cada tipo de día. Cada crash "
                                    "adicional deja un dump de ~1,4 GB y adelanta la fecha.")])]),
        dict(id="anexo-a", titulo="Anexo A · Calidad de los datos", anexo=True,
             tablas=[dict(df=calidad(d))]),
        dict(id="anexo-b", titulo="Anexo B · Eventos de Windows por día", anexo=True,
             tablas=[dict(df=eventos_por_dia(d["ev"]).reset_index().rename(columns={"evento": "Evento"}))]),
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
            if t.get("titulo"):
                r.append(f"**{t['titulo']}**\n")
            r += [md(t["df"]), ""] + [p + "\n" for p in t.get("nota", [])]
        if s.get("lista"):
            r.append(f"**{s.get('lista_titulo', '')}**\n")
            r += [f"- {x}" for x in s["lista"]] + [""]
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
    html_path = generar(SALIDAS / "reporte.html", "Reto 1 · Diagnóstico del incidente de PortalPagos (18/09/2026)",
                        "Andina Financiera (caso ficticio) · semana del 14 al 20 de septiembre de 2026 · horas en hora de Colombia",
                        kpis, secciones)

    print("\nResumen")
    for etiqueta, valor, detalle, _ in kpis:
        print(f"  - {etiqueta}: {valor} ({detalle})")
    print(f"\nReporte visual: {html_path}\nMarkdown:       {md_path}")
    if not args.no_abrir:
        webbrowser.open(html_path.as_uri())


if __name__ == "__main__":
    main()


