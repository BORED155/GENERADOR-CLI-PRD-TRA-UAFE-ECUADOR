"""Plantillas Excel que carga el UAFI (CLI/OPR/TRA<código><AAAAMMDD>.xlsx).

Formato de cada plantilla (igual a las que entrega el SISLAFT):
  fila 1: tipo de archivo (CLI/OPR/TRA), código de registro, fecha de corte, número de registros
  fila 2 en adelante: un registro por fila con todos los campos del nivel, en el orden de la estructura
  (las operaciones y transacciones repiten las llaves de su cliente/operación).
"""

from __future__ import annotations

import datetime as dt
import re
from pathlib import Path

from openpyxl import load_workbook

from .estructura import Archivo, Catalogos, Estructura
from .modelo import Registro, Reporte, normalizar


def nombre_plantilla(nivel: Archivo, rep: Reporte) -> str:
    return f"{nivel.prefijo}{rep.codigo}{rep.periodo}.xlsx"


def _celda(campo, valor: str):
    """Números y fechas como número (igual que las plantillas oficiales); el resto como texto."""
    if (campo.es_numero or campo.es_fecha) and valor.isdigit():
        return int(valor)
    return valor


def exportar(rep: Reporte, est: Estructura, carpeta: Path) -> list[Path]:
    carpeta = Path(carpeta)
    carpeta.mkdir(parents=True, exist_ok=True)
    filas: list[list[list]] = [[] for _ in est.niveles]
    for ruta, reg, ancestros in rep.recorrer():
        n = len(ruta) - 1
        if n < len(est.niveles):
            nivel = est.niveles[n]
            valores = rep.valores_completos(nivel, reg, ancestros)
            filas[n].append([_celda(c, valores.get(c.nombre, "")) for c in nivel.campos])
    rutas = []
    for nivel, datos in zip(est.niveles, filas):
        cabecera = [nivel.prefijo, int(rep.codigo), int(rep.periodo), len(datos)]
        anchos = [min(max(c.maximo, 6), 45) for c in nivel.campos]
        ruta = carpeta / nombre_plantilla(nivel, rep)
        plantilla = ruta_plantilla(nivel.prefijo)
        if plantilla is not None:
            escribir_desde_plantilla(plantilla, ruta, [cabecera, *datos])
        else:
            escribir_xlsx(ruta, [cabecera, *datos], anchos)
        rutas.append(ruta)
    return rutas


def ruta_plantilla(prefijo: str) -> Path | None:
    """Plantilla oficial (CLI/OPR/TRA) incluida con el programa, sin datos."""
    from importlib import resources

    ruta = Path(str(resources.files("resuapp").joinpath(f"datos/plantillas/{prefijo}.xlsx")))
    return ruta if ruta.is_file() else None


def _celdas_xml(filas: list[list], estilos: dict[str, str]) -> tuple[str, list[str], int]:
    cadenas: dict[str, int] = {}
    total = 0
    lineas = []
    for r, fila in enumerate(filas, start=1):
        celdas = []
        for c, valor in enumerate(fila):
            col = _columna(c)
            estilo = f' s="{estilos[col]}"' if r > 1 and col in estilos else ""
            if isinstance(valor, int):
                celdas.append(f'<c r="{col}{r}"{estilo}><v>{valor}</v></c>')
            else:
                total += 1
                indice = cadenas.setdefault(str(valor), len(cadenas))
                celdas.append(f'<c r="{col}{r}"{estilo} t="s"><v>{indice}</v></c>')
        lineas.append(f'<row r="{r}">{"".join(celdas)}</row>')
    return "".join(lineas), list(cadenas), total


def escribir_desde_plantilla(plantilla: Path, ruta: Path, filas: list[list]) -> None:
    """Copia la plantilla oficial y reemplaza solo las filas (y la tabla de textos)."""
    import zipfile

    with zipfile.ZipFile(plantilla) as zi:
        hoja = zi.read("xl/worksheets/sheet1.xml").decode("utf-8")
        fila2 = re.search(r'<row r="2"[^>]*>(.*?)</row>', hoja, re.S)
        estilos = dict(re.findall(r'<c r="([A-Z]+)2"[^>]*?\ss="(\d+)"', fila2.group(1))) if fila2 else {}
        filas_xml, cadenas, total = _celdas_xml(filas, estilos)
        ancho = max((len(f) for f in filas), default=1)
        hoja = re.sub(r"<sheetData\s*/>|<sheetData>.*?</sheetData>", lambda _m: f"<sheetData>{filas_xml}</sheetData>",
                      hoja, flags=re.S)
        hoja = re.sub(r'<dimension ref="[^"]*"/>', f'<dimension ref="A1:{_columna(ancho - 1)}{max(len(filas), 1)}"/>',
                      hoja)
        ns = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
        compartidas = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<sst {ns} count="{total}" '
                       f'uniqueCount="{len(cadenas)}">'
                       + "".join(f'<si><t xml:space="preserve">{_xml(t)}</t></si>' for t in cadenas) + "</sst>")
        tmp = Path(ruta).with_suffix(".tmp")
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zo:
            for info in zi.infolist():
                if info.filename == "xl/worksheets/sheet1.xml":
                    zo.writestr(info, hoja.encode("utf-8"))
                elif info.filename == "xl/sharedStrings.xml":
                    zo.writestr(info, compartidas.encode("utf-8"))
                elif info.filename == "xl/calcChain.xml":
                    continue
                else:
                    zo.writestr(info, zi.read(info))
    tmp.replace(ruta)


# ----------------------------------------------------------------------
# Escritura .xlsx propia: el UAFI usa Apache POI 3.9, que pierde el texto de las celdas guardadas
# como «inlineStr» (formato que usa openpyxl). Aquí el texto va en la tabla de cadenas compartidas
# (sharedStrings), como lo guarda Excel.
def _columna(i: int) -> str:
    letras = ""
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        letras = chr(65 + r) + letras
    return letras


def _xml(texto: str) -> str:
    # un carácter de control (a veces vienen al leer un PDF) deja el archivo ilegible
    texto = re.sub("[^\t\n\r\u0020-\ud7ff\ue000-\ufffd\U00010000-\U0010ffff]", "", texto)
    return (texto.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;"))


def escribir_xlsx(ruta: Path, filas: list[list], anchos: list[int] | None = None) -> None:
    import zipfile

    filas_xml, cadenas, total_cadenas = _celdas_xml(filas, {})
    ancho_max = max((len(f) for f in filas), default=1)
    cols = ""
    if anchos:
        cols = "<cols>" + "".join(f'<col min="{i}" max="{i}" width="{w}" customWidth="1"/>'
                                  for i, w in enumerate(anchos, start=1)) + "</cols>"
    ns = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
    nsr = 'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
    hoja = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<worksheet {ns} {nsr}>'
            f'<dimension ref="A1:{_columna(ancho_max - 1)}{max(len(filas), 1)}"/>{cols}'
            f'<sheetData>{filas_xml}</sheetData></worksheet>')
    compartidas = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<sst {ns} count="{total_cadenas}" '
                   f'uniqueCount="{len(cadenas)}">'
                   + "".join(f'<si><t xml:space="preserve">{_xml(t)}</t></si>' for t in cadenas) + "</sst>")
    tipos = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
             '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
             '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
             '<Default Extension="xml" ContentType="application/xml"/>'
             '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.'
             'spreadsheetml.sheet.main+xml"/>'
             '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-'
             'officedocument.spreadsheetml.worksheet+xml"/>'
             '<Override PartName="/xl/sharedStrings.xml" ContentType="application/vnd.openxmlformats-'
             'officedocument.spreadsheetml.sharedStrings+xml"/>'
             '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.'
             'spreadsheetml.styles+xml"/></Types>')
    rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/'
            'officeDocument" Target="xl/workbook.xml"/></Relationships>')
    libro = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<workbook {ns} {nsr}>'
             '<sheets><sheet name="Hoja1" sheetId="1" r:id="rId1"/></sheets></workbook>')
    libro_rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
                  '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                  '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/'
                  'relationships/worksheet" Target="worksheets/sheet1.xml"/>'
                  '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/'
                  'relationships/sharedStrings" Target="sharedStrings.xml"/>'
                  '<Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/'
                  'relationships/styles" Target="styles.xml"/></Relationships>')
    estilos = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<styleSheet {ns}>'
               '<fonts count="1"><font><sz val="11"/><name val="Calibri"/></font></fonts>'
               '<fills count="2"><fill><patternFill patternType="none"/></fill>'
               '<fill><patternFill patternType="gray125"/></fill></fills>'
               '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
               '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
               '<cellXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/></cellXfs>'
               '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>'
               '</styleSheet>')
    tmp = Path(ruta).with_suffix(".tmp")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", tipos)
        z.writestr("_rels/.rels", rels)
        z.writestr("xl/workbook.xml", libro)
        z.writestr("xl/_rels/workbook.xml.rels", libro_rels)
        z.writestr("xl/worksheets/sheet1.xml", hoja)
        z.writestr("xl/sharedStrings.xml", compartidas)
        z.writestr("xl/styles.xml", estilos)
    tmp.replace(ruta)


# ----------------------------------------------------------------------
def _texto(valor) -> str:
    if valor is None:
        return ""
    if isinstance(valor, (dt.datetime, dt.date)):
        return valor.strftime("%Y%m%d")
    if isinstance(valor, float):             # 85.125 con 3 decimales se confundiría con «85.125» de miles
        return str(int(valor)) if valor.is_integer() else f"{valor:.2f}"
    return str(valor).strip()


def _leer(ruta: Path) -> tuple[list[str], list[list[str]]]:
    libro = load_workbook(ruta, read_only=True, data_only=True)
    try:
        hoja = libro.worksheets[0]
        filas = [[_texto(v) for v in fila] for fila in hoja.iter_rows(values_only=True)]
    finally:
        libro.close()
    filas = [f for f in filas if any(f)]
    if not filas:
        raise ValueError(f"{ruta.name}: la plantilla está vacía.")
    return filas[0], filas[1:]


def _completar_catalogo(campo, valor: str, catalogos: Catalogos) -> str:
    """Excel convierte '0101' en 101: se recupera el cero si así existe en el catálogo."""
    if campo.tiene_catalogo and valor.isdigit() and not catalogos.contiene(campo.catalogo, valor):
        relleno = valor.zfill(campo.maximo)
        if catalogos.contiene(campo.catalogo, relleno):
            return relleno
    return valor


def importar(rutas: list[Path], est: Estructura, catalogos: Catalogos) -> tuple[Reporte, list[str]]:
    """Lee las plantillas (en cualquier orden) y arma el reporte. Devuelve (reporte, avisos)."""
    por_prefijo = {n.prefijo: i for i, n in enumerate(est.niveles)}
    leidas: dict[int, list[list[str]]] = {}
    codigo = corte = ""
    avisos: list[str] = []
    for ruta in map(Path, rutas):
        cabecera, datos = _leer(ruta)
        prefijo = (cabecera[0] if cabecera else "").upper()
        if prefijo not in por_prefijo:
            prefijo = next((p for p in por_prefijo if ruta.name.upper().startswith(p)), "")
        if prefijo not in por_prefijo:
            raise ValueError(f"{ruta.name}: no se reconoce el tipo de plantilla (CLI, OPR o TRA).")
        codigo = codigo or (cabecera[1] if len(cabecera) > 1 else "")
        corte = corte or (cabecera[2] if len(cabecera) > 2 else "")
        if len(cabecera) > 3 and cabecera[3].isdigit() and int(cabecera[3]) != len(datos):
            avisos.append(f"{ruta.name}: la cabecera dice {cabecera[3]} registros pero tiene {len(datos)}.")
        leidas[por_prefijo[prefijo]] = datos
    if len(corte) != 8 or not corte.isdigit():
        raise ValueError("No se pudo leer la fecha de corte de la cabecera de las plantillas.")
    rep = Reporte(codigo=codigo, anio=int(corte[:4]), mes=int(corte[4:6]))

    # índice: llaves completas del registro -> Registro, por nivel
    indices: list[dict[tuple, Registro]] = [{} for _ in est.niveles]
    for n, nivel in enumerate(est.niveles):
        for num, fila in enumerate(leidas.get(n, []), start=2):
            valores = {}
            for i, campo in enumerate(nivel.campos):
                valor = normalizar(campo, fila[i] if i < len(fila) else "")
                valores[campo.nombre] = _completar_catalogo(campo, valor, catalogos)
            llave = tuple(valores[c.nombre] for c in nivel.campos if c.llave in ("PK", "FK"))
            if llave in indices[n]:
                avisos.append(f"{nivel.prefijo} fila {num}: registro repetido, se omitió.")
                continue
            reg = Registro({c.nombre: valores[c.nombre] for c in nivel.propios if c.nombre not in ("CDR", "FCT")})
            indices[n][llave] = reg
            if n == 0:
                rep.clientes.append(reg)
                continue
            padre_nivel = est.niveles[n - 1]
            llave_padre = tuple(valores.get(c.nombre, "") for c in padre_nivel.campos if c.llave in ("PK", "FK"))
            padre = indices[n - 1].get(llave_padre)
            if padre is None:
                avisos.append(f"{nivel.prefijo} fila {num}: no se encontró a qué {padre_nivel.nombre.lower()} "
                              f"pertenece ({', '.join(llave_padre)}); se omitió.")
                continue
            padre.hijos.append(reg)
    return rep, avisos
