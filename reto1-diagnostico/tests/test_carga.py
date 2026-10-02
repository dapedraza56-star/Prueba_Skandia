"""Pruebas de las decisiones de limpieza que mas afectan las conclusiones."""
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from carga import archivos_unicos, cargar_httperr, cargar_iis, leer_w3c  # noqa: E402

W3C_DOS_ESQUEMAS = """#Software: Microsoft Internet Information Services 10.0
#Fields: date time cs-uri-stem sc-status
2026-09-17 03:00:00 /login 200
#Fields: date time cs-uri-stem sc-status X-Forwarded-For
2026-09-17 03:13:00 /login 500 190.1.2.3
linea corrupta
"""


def test_respeta_cambio_de_esquema(tmp_path):
    f = tmp_path / "u_ex.log"
    f.write_text(W3C_DOS_ESQUEMAS)
    df = leer_w3c(f)
    assert len(df) == 2  # la linea corrupta se descarta
    assert pd.isna(df.loc[0, "X-Forwarded-For"])
    assert df.loc[1, "X-Forwarded-For"] == "190.1.2.3"


def test_descarta_archivos_con_contenido_identico(tmp_path):
    (tmp_path / "u_ex1.log").write_text("igual")
    (tmp_path / "u_ex1 - copia.log").write_text("igual")
    (tmp_path / "u_ex2.log").write_text("distinto")
    cargar, descartados = archivos_unicos(list(tmp_path.glob("*.log")))
    assert [p.name for p in cargar] == ["u_ex1.log", "u_ex2.log"]
    assert descartados[0][0].name == "u_ex1 - copia.log"


def test_kit_semana_completa_en_hora_colombia():
    iis, descartados = cargar_iis()
    assert len(descartados) == 1
    # UTC -> Colombia: la semana va del lunes 14 00:00 al domingo 20 23:59
    assert iis.ts.min() >= pd.Timestamp("2026-09-14 00:00")
    assert iis.ts.max() < pd.Timestamp("2026-09-21 00:00")


def test_caida_en_httperr_coincide_con_ticket():
    h = cargar_httperr()
    caida = h[h["sc-status"] == 503]
    # Ticket T-10255: reinicio manual a las 15:04 hora Colombia
    assert caida.ts.min() == pd.Timestamp("2026-09-18 14:38:00")
    assert caida.ts.max() < pd.Timestamp("2026-09-18 15:04:30")
