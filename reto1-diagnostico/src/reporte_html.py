"""Genera un reporte HTML autocontenido (sin internet) con los resultados del Reto 1.

Cada seccion es un dict:
    id, titulo, texto (lista de parrafos; **negrita** permitida), tabla (DataFrame o None),
    figuras (lista de rutas PNG), resaltar (funcion fila -> clase CSS o "")
Los indicadores de la cabecera son una lista de (etiqueta, valor, detalle, tono)
con tono en {"critico", "alerta", "ok", "neutro"}.
"""
from __future__ import annotations

import base64
import html
import re
from pathlib import Path

import pandas as pd

CSS = """
:root{--bg:#f6f6f3;--surface:#fcfcfb;--ink:#0b0b0b;--ink-2:#52514e;--line:#e3e2dc;
--accent:#2a78d6;--crit:#c62f2f;--crit-bg:#fdecec;--warn:#9a6700;--warn-bg:#fdf4dc;
--ok:#1a7f37;--ok-bg:#e7f5ea;--chip:#efeee9}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#121211;--surface:#1a1a19;
--ink:#f4f4f2;--ink-2:#c3c2b7;--line:#2e2e2b;--accent:#3987e5;--crit:#ff8a85;--crit-bg:#3a1a1a;
--warn:#f0c060;--warn-bg:#352a10;--ok:#6fd38a;--ok-bg:#15301d;--chip:#262624}}
:root[data-theme="dark"]{--bg:#121211;--surface:#1a1a19;--ink:#f4f4f2;--ink-2:#c3c2b7;--line:#2e2e2b;
--accent:#3987e5;--crit:#ff8a85;--crit-bg:#3a1a1a;--warn:#f0c060;--warn-bg:#352a10;--ok:#6fd38a;
--ok-bg:#15301d;--chip:#262624}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.55 "Segoe UI",system-ui,sans-serif}
header{padding:28px 32px 8px;max-width:1280px;margin:auto}
h1{font-size:24px;margin:0 0 4px}
.sub{color:var(--ink-2);font-size:13.5px}
nav{position:sticky;top:0;z-index:5;background:var(--bg);border-bottom:1px solid var(--line)}
nav .in{max-width:1280px;margin:auto;padding:8px 32px;display:flex;gap:6px;flex-wrap:wrap;align-items:center}
nav a{color:var(--ink-2);text-decoration:none;font-size:13px;padding:4px 10px;border-radius:999px}
nav a:hover{background:var(--chip);color:var(--ink)}
nav button{margin-left:auto;border:1px solid var(--line);background:var(--surface);color:var(--ink);
border-radius:8px;padding:4px 10px;cursor:pointer;font-size:13px}
main{max-width:1280px;margin:auto;padding:8px 32px 60px}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:12px;margin:18px 0 8px}
.kpi{background:var(--surface);border:1px solid var(--line);border-radius:12px;padding:14px 16px;
border-left:4px solid var(--line)}
.kpi .l{font-size:12.5px;color:var(--ink-2)}
.kpi .v{font-size:26px;font-weight:650;margin:2px 0;font-variant-numeric:tabular-nums}
.kpi .d{font-size:12px;color:var(--ink-2)}
.kpi.critico{border-left-color:var(--crit)}.kpi.critico .v{color:var(--crit)}
.kpi.alerta{border-left-color:var(--warn)}.kpi.alerta .v{color:var(--warn)}
.kpi.ok{border-left-color:var(--ok)}
section{background:var(--surface);border:1px solid var(--line);border-radius:14px;padding:20px 22px;
margin:18px 0;scroll-margin-top:56px}
section h2{font-size:18px;margin:0 0 8px}
section p{margin:6px 0;color:var(--ink);max-width:95ch}
.tw{overflow-x:auto;margin-top:12px;border:1px solid var(--line);border-radius:10px}
table{border-collapse:collapse;width:100%;font-size:13.5px}
th{position:sticky;top:0;background:var(--chip);text-align:left;font-weight:600;padding:8px 10px;
cursor:pointer;white-space:nowrap;user-select:none}
th:after{content:" \\2195";color:var(--ink-2);font-size:11px}
th.asc:after{content:" \\2191"}th.desc:after{content:" \\2193"}
td{padding:7px 10px;border-top:1px solid var(--line);vertical-align:top}
td:first-child{white-space:nowrap}
td.n{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
tr.critico td{background:var(--crit-bg)}tr.alerta td{background:var(--warn-bg)}tr.ok td{background:var(--ok-bg)}
tr.total td{font-weight:650;border-top:2px solid var(--ink-2)}
.chip{display:inline-block;padding:1px 8px;border-radius:999px;font-size:12px;background:var(--chip);white-space:nowrap}
.chip.critico{background:var(--crit-bg);color:var(--crit)}.chip.alerta{background:var(--warn-bg);color:var(--warn)}
.chip.ok{background:var(--ok-bg);color:var(--ok)}
.filtro{margin-top:10px;padding:6px 10px;width:min(360px,100%);border:1px solid var(--line);border-radius:8px;
background:var(--bg);color:var(--ink)}
figure{margin:16px 0 0}figure img{max-width:100%;border-radius:10px;border:1px solid var(--line);background:#fff}
figcaption{font-size:12.5px;color:var(--ink-2);margin-top:4px}
footer{color:var(--ink-2);font-size:12.5px;text-align:center;padding:20px}
@media (max-width:640px){header,main,nav .in{padding-left:16px;padding-right:16px}.kpi .v{font-size:22px}}
@media print{nav{display:none}section{break-inside:avoid}}
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
document.querySelectorAll('input.filtro').forEach(inp=>inp.addEventListener('input',()=>{
  const q=inp.value.toLowerCase();
  document.getElementById(inp.dataset.t).querySelectorAll('tbody tr')
    .forEach(r=>r.style.display=r.innerText.toLowerCase().includes(q)?'':'none');
}));
const tema=document.getElementById('tema');
tema.addEventListener('click',()=>{
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
    if isinstance(v, (bool,)) or v is None:
        return html.escape(str(v)), None
    if isinstance(v, (int, float)) and not pd.isna(v):
        if float(v).is_integer():
            s = f"{int(v):,}".replace(",", ".")
        else:
            s = f"{v:,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")
        return s, str(float(v))
    if isinstance(v, float) and pd.isna(v):
        return "—", "-1e18"
    return _inline(str(v)), None


def _tabla(df: pd.DataFrame, tid: str, resaltar=None, chips: dict | None = None) -> str:
    cab = "".join(f"<th>{html.escape(str(c))}</th>" for c in df.columns)
    filas = []
    for _, fila in df.iterrows():
        clase = resaltar(fila) if resaltar else ""
        celdas = []
        for c, v in fila.items():
            if chips and c in chips:
                tono = chips[c](v)
                celdas.append(f'<td><span class="chip {tono}">{html.escape(str(v))}</span></td>')
                continue
            txt, orden = _num(v)
            if orden is not None:
                celdas.append(f'<td class="n" data-v="{orden}">{txt}</td>')
            else:
                celdas.append(f"<td>{txt}</td>")
        filas.append(f'<tr class="{clase}">{"".join(celdas)}</tr>')
    return (f'<div class="tw"><table class="sort" id="{tid}"><thead><tr>{cab}</tr></thead>'
            f'<tbody>{"".join(filas)}</tbody></table></div>')


def _figura(path: Path) -> str:
    b64 = base64.b64encode(path.read_bytes()).decode()
    return (f'<figure><img alt="{html.escape(path.stem)}" src="data:image/png;base64,{b64}">'
            f"<figcaption>{html.escape(path.name)}</figcaption></figure>")


def generar(destino: Path, titulo: str, subtitulo: str, kpis: list, secciones: list) -> Path:
    nav = "".join(f'<a href="#{s["id"]}">{html.escape(s["titulo"])}</a>' for s in secciones)
    tarjetas = "".join(
        f'<div class="kpi {tono}"><div class="l">{html.escape(l)}</div><div class="v">{html.escape(v)}</div>'
        f'<div class="d">{_inline(d)}</div></div>' for l, v, d, tono in kpis)
    cuerpo = []
    for s in secciones:
        partes = [f'<section id="{s["id"]}"><h2>{html.escape(s["titulo"])}</h2>']
        partes += [f"<p>{_inline(p)}</p>" for p in s.get("texto", [])]
        for i, t in enumerate(s.get("tablas", [])):
            tid = f'{s["id"]}-t{i}'
            if t.get("filtro"):
                partes.append(f'<input class="filtro" data-t="{tid}" placeholder="Filtrar filas…">')
            partes.append(_tabla(t["df"], tid, t.get("resaltar"), t.get("chips")))
            partes += [f"<p>{_inline(p)}</p>" for p in t.get("nota", [])]
        partes += [_figura(f) for f in s.get("figuras", [])]
        partes.append("</section>")
        cuerpo.append("".join(partes))
    doc = f"""<!doctype html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{html.escape(titulo)}</title>
<style>{CSS}</style></head><body>
<header><h1>{html.escape(titulo)}</h1><div class="sub">{_inline(subtitulo)}</div></header>
<nav><div class="in">{nav}<button id="tema" type="button">Claro / oscuro</button></div></nav>
<main><div class="kpis">{tarjetas}</div>{''.join(cuerpo)}</main>
<footer>Generado por reto1-diagnostico/src/analisis.py · no editar a mano</footer>
<script>{JS}</script></body></html>"""
    destino.write_text(doc, encoding="utf-8")
    return destino
