"""Datos de prueba ficticios: un UAFI falso con la estructura del sector inmobiliario y un catálogo mínimo."""

from __future__ import annotations

import os
import zipfile
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

CODIGO = "99999"
CAMPOS = {
    "CLIENTE": [("TID", "string", 1, 1, "PK", "TI"), ("IDE", "string", 3, 20, "PK", "NO"),
                ("NRS", "string", 2, 150, "NK", "NO"), ("AEC", "string", 3, 10, "NK", "AE"),
                ("IMT", "long", 1, 16, "NK", "NO"), ("NAC", "string", 3, 3, "NK", "N"),
                ("DIR", "string", 8, 150, "NK", "NO"), ("CCC", "string", 4, 4, "NK", "C"),
                ("CDR", "string", 4, 5, "PK", "NO"), ("FCT", "date", 8, 8, "PK", "NO")],
    "OPERACION": [("TID", "string", 1, 1, "FK", "TI"), ("IDE", "string", 3, 20, "FK", "NO"),
                  ("CDR", "string", 4, 5, "FK", "NO"), ("FCT", "date", 8, 8, "FK", "NO"),
                  ("NCT", "string", 1, 40, "PK", "NO"), ("VTO", "long", 1, 16, "NK", "NO"),
                  ("FDO", "date", 8, 8, "NK", "NO"), ("TTB", "string", 3, 3, "NK", "TB"),
                  ("ADB", "long", 1, 16, "NK", "NO"), ("DRB", "string", 3, 150, "NK", "NO"),
                  ("CCO", "string", 4, 4, "NK", "C"), ("PUB", "string", 2, 3, "NK", "P")],
    "TRANSACCION": [("TID", "string", 1, 1, "FK", "TI"), ("IDE", "string", 3, 20, "FK", "NO"),
                    ("CDR", "string", 4, 5, "FK", "NO"), ("FCT", "date", 8, 8, "FK", "NO"),
                    ("NCT", "string", 1, 40, "FK", "NO"), ("FTR", "date", 8, 8, "PK", "NO"),
                    ("NFA", "string", 1, 40, "PK", "NO"),
                    *[(n, "long", 1, 16, "NK", "NO") for n in
                      ("VDE", "VCR", "VEF", "VCH", "VBB", "VSR", "VTC", "VFC", "VCV", "VVT")],
                    ("MND", "string", 3, 3, "NK", "TM"), ("CAT", "string", 8, 10, "NK", "O"),
                    ("TTR", "string", 2, 3, "PK", "TT"), ("RPT", "string", 1, 1, "NK", "PT"),
                    ("TIT", "string", 0, 1, "NK", "TI"), ("IDT", "string", 0, 20, "NK", "NO"),
                    ("NRT", "string", 0, 150, "NK", "NO")],
}


def _xml_archivo(nombres: list[str], etiqueta: str = "archivo") -> str:
    nombre, resto = nombres[0], nombres[1:]
    campos = "".join(
        f"<campo><nombre>{n}</nombre><tipo>{t}</tipo><maximo>{mx}</maximo><minimo>{mn}</minimo>"
        f"<label>{n} ETIQUETA</label><llavePrimaria>{k}</llavePrimaria><catalogo>{c}</catalogo></campo>"
        for n, t, mn, mx, k, c in CAMPOS[nombre])
    hijo = _xml_archivo(resto, "archivos") if resto else ""
    return f"<{etiqueta}><nombre>{nombre}</nombre>{campos}{hijo}</{etiqueta}>"


DATOS_SUJETO = ("<?xml version='1.0' encoding='UTF-8'?><resu><razonSocial>X</razonSocial><estructura>"
                "<sector>INMOBILIARIAS Y CONSTRUCTORAS</sector>"
                + _xml_archivo(["CLIENTE", "OPERACION", "TRANSACCION"]) + "</estructura></resu>")

CATALOGOS = {
    "tipoIdentificacion": {"C": "CEDULA", "R": "RUC", "P": "PASAPORTE", "A": "ANALOGO", "X": "N/A"},
    "nacionalidad": {"ECU": "ECUADOR", "COL": "COLOMBIA"},
    "canton": {"1701": "QUITO", "0101": "CUENCA", "0000": "N/A"},
    "actividadEconomica": {"F4100": "CONSTRUCCION DE EDIFICIOS", "L6810": "ACTIVIDADES INMOBILIARIAS"},
    "tipoMoneda": {"USD": "DOLAR ESTADOUNIDENSE"},
    "pais": {"EC": "ECUADOR"},
    "tipoBien": {"CAS": "CASA", "OFI": "OFICINAS", "DEP": "DEPARTAMENTOS"},
    "tipoTransaccion": {c: n for c, n in [("91", "COMPRA BIENES INMUEBLES"), ("92", "VENTA BIENES INMUEBLES"),
                                          ("94", "PERMUTAS"), ("95", "APORTE INICIAL"), ("96", "APORTES"),
                                          ("97", "RESERVA"), ("98", "RESCILIACION"), ("99", "CESION"),
                                          ("103", "OBRAS")]},
    "tipoPago": {"0": "NO APLICA", "1": "PROPIOS", "2": "DE TERCEROS", "3": "MIXTO"},
}
CATALOGOS_XML = "<?xml version='1.0' encoding='UTF-8'?><catalogos>" + "".join(
    f"<{t}><codigo>{c}</codigo><nombre>{n}</nombre></{t}>" for t, filas in CATALOGOS.items()
    for c, n in filas.items()) + "</catalogos>"


def crear_uafi_falso(carpeta: Path) -> Path:
    recursos = carpeta / "bin" / "ec/gob/uaf/sislaft/uafi/util/xml"
    recursos.mkdir(parents=True)
    (recursos / "DatosSujeto.xml").write_text(DATOS_SUJETO, "utf-8")
    (recursos / "Catalogos.xml").write_text(CATALOGOS_XML, "utf-8")
    (carpeta / "lib").mkdir()
    (carpeta / "lib" / "vacio.txt").write_text("")
    return carpeta


@pytest.fixture
def datos(tmp_path, monkeypatch):
    monkeypatch.setenv("RESUAPP_DATOS", str(tmp_path / "datos"))
    return tmp_path / "datos"


@pytest.fixture
def uafi_falso(tmp_path) -> Path:
    return crear_uafi_falso(tmp_path / "uafi")


@pytest.fixture
def uafi_zip(tmp_path, uafi_falso) -> Path:
    destino = tmp_path / "uafi.zip"
    with zipfile.ZipFile(destino, "w") as z:
        for p in uafi_falso.rglob("*"):
            z.write(p, Path("uafi") / p.relative_to(uafi_falso))
    return destino


@pytest.fixture
def estructura_y_catalogos(uafi_falso):
    from resuapp.estructura import cargar_de_uafi

    return cargar_de_uafi(uafi_falso)
