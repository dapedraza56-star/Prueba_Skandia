"""Genera un reporte HTML autocontenido (sin internet) con los resultados del Reto 1.

Usa la paleta corporativa de Skandia tomada del CSS publico de skandia.co:
verde de marca #00C83C (y tonos #009047 / #007444 para texto y lineas), grises
#3F3F3F / #362E2E, fondo #F5F5F5 y rojo de error #E12B1C. Tipografia Montserrat
si esta instalada (no se descarga nada).

Cada seccion es un dict:
    id, titulo, texto (parrafos; **negrita** y `codigo` permitidos),
    tablas (lista de dict: df, titulo, nota, resaltar(fila)->clase, chips{col: fn(valor)->clase}),
    lista + lista_titulo (viñetas), figuras (rutas PNG), anexo (True = plegable)
Los indicadores son una lista de (etiqueta, valor, detalle, tono) con tono en
{"critico", "alerta", "ok", "neutro"}.
"""
from __future__ import annotations

import base64
import html
import re
from pathlib import Path

import pandas as pd

CSS = """
:root{--marca:#00C83C;--marca-osc:#007444;--marca-med:#009047;--marca-suave:#CEFCC9;
--bg:#F5F5F5;--surface:#FFFFFF;--ink:#362E2E;--ink-2:#666666;--line:#E9E9E9;--chip:#F4F4F4;
--crit:#E12B1C;--crit-bg:#FDECEA;--warn:#8A5A00;--warn-bg:#FFF4D6;--ok:#007444;--ok-bg:#E6F9E8}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--marca:#37DE59;--marca-osc:#5FED73;
--marca-med:#37DE59;--marca-suave:#103A20;--bg:#202020;--surface:#2B2B2B;--ink:#F4F4F4;--ink-2:#BDBDBD;
--line:#3F3F3F;--chip:#363636;--crit:#FF7B70;--crit-bg:#3D1715;--warn:#F2C25B;--warn-bg:#3A2C0E;
--ok:#5FED73;--ok-bg:#12331C}}
:root[data-theme="dark"]{--marca:#37DE59;--marca-osc:#5FED73;--marca-med:#37DE59;--marca-suave:#103A20;
--bg:#202020;--surface:#2B2B2B;--ink:#F4F4F4;--ink-2:#BDBDBD;--line:#3F3F3F;--chip:#363636;--crit:#FF7B70;
--crit-bg:#3D1715;--warn:#F2C25B;--warn-bg:#3A2C0E;--ok:#5FED73;--ok-bg:#12331C}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
font:15px/1.55 Montserrat,"Montserrat-Regular","Segoe UI",system-ui,sans-serif}
.franja{height:6px;background:var(--marca)}
header{background:var(--surface);border-bottom:1px solid var(--line)}
header .in{max-width:1200px;margin:auto;padding:22px 32px 18px}
.eyebrow{color:var(--marca-osc);font-weight:700;font-size:12.5px;letter-spacing:.06em;text-transform:uppercase}
h1{font-size:24px;margin:4px 0;font-weight:700}
.sub{color:var(--ink-2);font-size:13.5px}
nav{position:sticky;top:0;z-index:5;background:var(--surface);border-bottom:1px solid var(--line)}
nav .in{max-width:1200px;margin:auto;padding:6px 32px;display:flex;gap:4px;flex-wrap:wrap;align-items:center}
nav a{color:var(--ink);text-decoration:none;font-size:13px;font-weight:600;padding:6px 12px;border-radius:999px}
nav a:hover{background:var(--marca-suave);color:var(--marca-osc)}
nav button{margin-left:auto;border:1px solid var(--line);background:var(--surface);color:var(--ink);
border-radius:999px;padding:5px 12px;cursor:pointer;font:inherit;font-size:12.5px}
main{max-width:1200px;margin:auto;padding:8px 32px 60px}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:14px;margin:22px 0 6px}
.kpi{background:var(--surface);border-radius:14px;padding:16px 18px;border-top:4px solid var(--marca)}
.kpi .l{font-size:12.5px;color:var(--ink-2);font-weight:600}
.kpi .v{font-size:28px;font-weight:700;margin:4px 0;font-variant-numeric:tabular-nums}
.kpi .d{font-size:12.5px;color:var(--ink-2)}
.kpi.critico{border-top-color:var(--crit)}.kpi.critico .v{color:var(--crit)}
.kpi.alerta{border-top-color:#F2B705}.kpi.alerta .v{color:var(--warn)}
section,details{background:var(--surface);border-radius:16px;padding:22px 24px;margin:18px 0;scroll-margin-top:60px}
section h2,summary{font-size:18px;margin:0 0 10px;font-weight:700}
section h2:before{content:"";display:inline-block;width:6px;height:18px;background:var(--marca);
border-radius:3px;margin-right:10px;vertical-align:-2px}
summary{cursor:pointer;margin:0;color:var(--ink-2)}
details[open] summary{margin-bottom:10px}
h3{font-size:14.5px;margin:18px 0 0;color:var(--marca-osc)}
p{margin:8px 0;max-width:100ch}
ul{margin:6px 0 0;padding-left:20px}li{margin:4px 0}
code{background:var(--chip);padding:1px 5px;border-radius:5px;font-size:12.5px}
.tw{overflow-x:auto;margin-top:10px;border:1px solid var(--line);border-radius:12px}
table{border-collapse:collapse;width:100%;font-size:13.5px}
th{background:var(--marca-suave);color:var(--marca-osc);text-align:left;font-weight:700;padding:9px 12px;
cursor:pointer;white-space:nowrap;user-select:none}
th:after{content:" \\2195";opacity:.5;font-size:11px}th.asc:after{content:" \\2191";opacity:1}
th.desc:after{content:" \\2193";opacity:1}
td{padding:8px 12px;border-top:1px solid var(--line);vertical-align:top}
td.k{white-space:nowrap;font-weight:600}
td.n{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
tr.critico td{background:var(--crit-bg)}tr.alerta td{background:var(--warn-bg)}tr.ok td{background:var(--ok-bg)}
tr.total td{font-weight:700;border-top:2px solid var(--ink)}
.chip{display:inline-block;padding:2px 10px;border-radius:999px;font-size:12px;font-weight:600;
background:var(--chip);white-space:nowrap}
.chip.critico{background:var(--crit-bg);color:var(--crit)}.chip.alerta{background:var(--warn-bg);color:var(--warn)}
.chip.ok{background:var(--ok-bg);color:var(--ok)}
.nota{background:var(--chip);border-left:4px solid var(--marca);padding:10px 14px;border-radius:8px;margin-top:12px}
figure{margin:18px 0 0}figure img{max-width:100%;border-radius:12px;border:1px solid var(--line);background:#fff}
footer{color:var(--ink-2);font-size:12.5px;text-align:center;padding:24px}
@media (max-width:640px){header .in,main,nav .in{padding-left:16px;padding-right:16px}.kpi .v{font-size:23px}}
@media print{nav,.franja{display:none}section,details{break-inside:avoid}}
"""

JS = """
document.querySelectorAll('table.sort').forEach(t=>{
  t.querySelectorAll('th').forEach((th,i)=>th.addEventListener('click',()=>{
    const asc=!th.classList.contains('asc');
    t.querySelectorAll('th').forEach(h=>h.classList.remove('asc','desc'));
    th.classList.add(asc?'asc':'desc');
    const b=t.tBodies[0], filas=[...b.rows].filter(r=>!r.classList.contains('total'));
    const tot=[...b.rows].filter(r=>r.classList.contains('total'));
    const val=r=>{const c=r.cells[i];return c.dataset.v!==undefined?parseFloat(c.dataset.v):c.innerText};
    filas.sort((a,c)=>{const x=val(a),y=val(c);
      const r=(typeof x==='number'&&typeof y==='number')?x-y:String(x).localeCompare(String(y),'es');
      return asc?r:-r});
    filas.concat(tot).forEach(r=>b.appendChild(r));
  }));
});
document.getElementById('tema').addEventListener('click',()=>{
  const r=document.documentElement, oscuro=r.dataset.theme? r.dataset.theme==='dark'
    : matchMedia('(prefers-color-scheme: dark)').matches;
  r.dataset.theme=oscuro?'light':'dark';
});
"""


def _inline(texto: str) -> str:
    t = html.escape(texto)
    t = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", t)
    return re.sub(r"`(.+?)`", r"<code>\1</code>", t)


def _num(v) -> tuple[str, str | None]:
    """Formato es-CO: miles con punto, decimales con coma. Devuelve (texto, valor para ordenar)."""
    if isinstance(v, bool) or v is None:
        return html.escape(str(v)), None
    if isinstance(v, float) and pd.isna(v):
        return "—", "-1e18"
    if isinstance(v, (int, float)):
        if float(v).is_integer():
            s = f"{int(v):,}".replace(",", ".")
        else:
            s = f"{v:,.2f}".rstrip("0").rstrip(".").replace(",", "_").replace(".", ",").replace("_", ".")
        return s, str(float(v))
    return _inline(str(v)), None


def _tabla(df: pd.DataFrame, tid: str, resaltar=None, chips: dict | None = None) -> str:
    cab = "".join(f"<th>{html.escape(str(c))}</th>" for c in df.columns)
    filas = []
    for _, fila in df.iterrows():
        clase = resaltar(fila) if resaltar else ""
        celdas = []
        for j, (c, v) in enumerate(fila.items()):
            if j == 0 and isinstance(v, str) and len(v) <= 22:
                celdas.append(f'<td class="k">{_inline(v)}</td>')
                continue
            if chips and c in chips:
                celdas.append(f'<td><span class="chip {chips[c](v)}">{html.escape(str(v))}</span></td>')
                continue
            txt, orden = _num(v)
            celdas.append(f'<td class="n" data-v="{orden}">{txt}</td>' if orden is not None else f"<td>{txt}</td>")
        filas.append(f'<tr class="{clase}">{"".join(celdas)}</tr>')
    return (f'<div class="tw"><table class="sort" id="{tid}"><thead><tr>{cab}</tr></thead>'
            f'<tbody>{"".join(filas)}</tbody></table></div>')


def _figura(path: Path) -> str:
    b64 = base64.b64encode(path.read_bytes()).decode()
    return f'<figure><img alt="{html.escape(path.stem)}" src="data:image/png;base64,{b64}"></figure>'


def _seccion(s: dict) -> str:
    partes = [f"<p>{_inline(p)}</p>" for p in s.get("texto", [])]
    for i, t in enumerate(s.get("tablas", [])):
        if t.get("titulo"):
            partes.append(f"<h3>{html.escape(t['titulo'])}</h3>")
        partes.append(_tabla(t["df"], f'{s["id"]}-t{i}', t.get("resaltar"), t.get("chips")))
        partes += [f'<p class="nota">{_inline(p)}</p>' for p in t.get("nota", [])]
    if s.get("lista"):
        partes.append(f"<h3>{html.escape(s.get('lista_titulo', ''))}</h3><ul>"
                      + "".join(f"<li>{_inline(x)}</li>" for x in s["lista"]) + "</ul>")
    partes += [_figura(f) for f in s.get("figuras", [])]
    if s.get("anexo"):
        return f'<details id="{s["id"]}"><summary>{html.escape(s["titulo"])}</summary>{"".join(partes)}</details>'
    return f'<section id="{s["id"]}"><h2>{html.escape(s["titulo"])}</h2>{"".join(partes)}</section>'


def generar(destino: Path, titulo: str, subtitulo: str, kpis: list, secciones: list,
            eyebrow: str = "Prueba técnica · Observabilidad y Automatización") -> Path:
    nav = "".join(f'<a href="#{s["id"]}">{html.escape(s["titulo"].split(". ", 1)[-1])}</a>'
                  for s in secciones if not s.get("anexo"))
    tarjetas = "".join(
        f'<div class="kpi {tono}"><div class="l">{html.escape(lab)}</div><div class="v">{html.escape(v)}</div>'
        f'<div class="d">{_inline(det)}</div></div>' for lab, v, det, tono in kpis)
    doc = f"""<!doctype html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{html.escape(titulo)}</title>
<style>{CSS}</style></head><body>
<div class="franja"></div>
<header><div class="in"><div class="eyebrow">{html.escape(eyebrow)}</div><h1>{html.escape(titulo)}</h1>
<div class="sub">{_inline(subtitulo)}</div></div></header>
<nav><div class="in">{nav}<button id="tema" type="button">Claro / oscuro</button></div></nav>
<main><div class="kpis">{tarjetas}</div>{''.join(_seccion(s) for s in secciones)}</main>
<footer>Generado por reto1-diagnostico/src/analisis.py · datos sintéticos del kit de la prueba</footer>
<script>{JS}</script></body></html>"""
    destino.write_text(doc, encoding="utf-8")
    return destino
