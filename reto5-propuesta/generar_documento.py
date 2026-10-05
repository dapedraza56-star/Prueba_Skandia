"""Convierte propuesta_90_dias.md en HTML (paleta Skandia) y PDF A4, y verifica que el PDF no pase de 2 paginas.

Uso:  python reto5-propuesta/generar_documento.py
El PDF se imprime con Microsoft Edge en modo headless (viene con Windows). Sin dependencias externas.
"""
from __future__ import annotations

import html
import re
import shutil
import subprocess
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
MD = BASE / "propuesta_90_dias.md"
HTML = BASE / "propuesta_90_dias.html"
PDF = BASE / "propuesta_90_dias.pdf"
MAX_PAGINAS = 2

CSS = """
@page{size:A4;margin:12mm 13mm}
:root{--marca:#00C83C;--osc:#007444;--suave:#E6F9E8;--ink:#362E2E;--ink2:#666;--line:#DADADA}
*{box-sizing:border-box}
body{font:8.6pt/1.38 Montserrat,"Segoe UI",Arial,sans-serif;color:var(--ink);margin:0;max-width:190mm;margin:auto}
.franja{height:5px;background:var(--marca);margin-bottom:8px}
h1{font-size:15pt;margin:0 0 4px}
h2{font-size:10.5pt;margin:10px 0 4px;color:var(--osc);border-left:4px solid var(--marca);padding-left:7px}
p{margin:4px 0}
table{border-collapse:collapse;width:100%;margin:4px 0 6px;font-size:7.7pt;page-break-inside:auto}
tr{page-break-inside:avoid}
th{background:var(--suave);color:var(--osc);text-align:left;padding:3px 5px;font-weight:700}
td{padding:3px 5px;border-top:1px solid var(--line);vertical-align:top}
ol,ul{margin:3px 0;padding-left:18px}li{margin:2px 0}
strong{font-weight:700}
@media screen{body{font-size:10.5pt;padding:24px}table{font-size:9.5pt}}
"""


def inline(t: str) -> str:
    t = html.escape(t)
    t = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", t)
    return re.sub(r"`(.+?)`", r"<code>\1</code>", t)


def md_a_html(md: str) -> str:
    out, i, lineas = [], 0, md.splitlines()
    while i < len(lineas):
        l = lineas[i]
        if l.startswith("# "):
            out.append(f"<h1>{inline(l[2:])}</h1>")
        elif l.startswith("## "):
            out.append(f"<h2>{inline(l[3:])}</h2>")
        elif l.startswith("|"):
            filas = []
            while i < len(lineas) and lineas[i].startswith("|"):
                filas.append([c.strip() for c in lineas[i].strip("|").split("|")])
                i += 1
            cab, cuerpo = filas[0], [f for f in filas[2:]]
            out.append("<table><thead><tr>" + "".join(f"<th>{inline(c)}</th>" for c in cab) + "</tr></thead><tbody>"
                       + "".join("<tr>" + "".join(f"<td>{inline(c)}</td>" for c in f) + "</tr>" for f in cuerpo)
                       + "</tbody></table>")
            continue
        elif re.match(r"^\d+\. ", l):
            items = []
            while i < len(lineas) and re.match(r"^\d+\. ", lineas[i]):
                items.append(re.sub(r"^\d+\. ", "", lineas[i]))
                i += 1
            out.append("<ol>" + "".join(f"<li>{inline(x)}</li>" for x in items) + "</ol>")
            continue
        elif l.strip():
            out.append(f"<p>{inline(l)}</p>")
        i += 1
    return "\n".join(out)


def edge() -> str | None:
    for c in [r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
              r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"]:
        if Path(c).exists():
            return c
    return shutil.which("msedge")


def main() -> int:
    cuerpo = md_a_html(MD.read_text(encoding="utf-8"))
    HTML.write_text(f'<!doctype html><html lang="es"><head><meta charset="utf-8">'
                    f'<meta name="viewport" content="width=device-width,initial-scale=1">'
                    f'<title>Propuesta 90 días</title><style>{CSS}</style></head>'
                    f'<body><div class="franja"></div>{cuerpo}</body></html>', encoding="utf-8")
    exe = edge()
    if not exe:
        print(f"HTML generado en {HTML}. No se encontro Edge para generar el PDF.")
        return 0
    subprocess.run([exe, "--headless=new", "--disable-gpu", "--no-pdf-header-footer",
                    f"--print-to-pdf={PDF}", HTML.as_uri()], check=True, capture_output=True, timeout=120)
    paginas = len(re.findall(rb"/Type\s*/Page[^s]", PDF.read_bytes()))
    print(f"HTML: {HTML}\nPDF:  {PDF} ({paginas} paginas)")
    if paginas > MAX_PAGINAS:
        print(f"ERROR: la propuesta supera {MAX_PAGINAS} paginas")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
