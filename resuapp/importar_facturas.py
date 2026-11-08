"""Convierte facturas de venta en clientes, operaciones y transacciones del reporte RESU.

Cada factura del mes produce:
  * el CLIENTE (si no está ya en el reporte), con los datos de la factura y los que se recuerdan
    del directorio de clientes de la empresa (actividad económica, cantón, ingresos…);
  * una OPERACIÓN con número = número de la factura, valor = total de la factura (sin decimales);
  * una TRANSACCIÓN con la fecha, el número de factura y el valor en el instrumento monetario
    que corresponde a la forma de pago del SRI.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from decimal import Decimal

from .empresas import Empresa
from .facturas import Factura, NoLeido
from .modelo import INSTRUMENTOS, PROVINCIAS, Registro, Reporte, sin_tildes
from .reglas import INSTRUMENTOS_POR_TRANSACCION

LISTA, AVISO, OMITIR = "lista", "aviso", "omitir"

TIPO_ID = {"04": "R", "05": "C", "06": "P", "08": "A"}
NOMBRE_INSTRUMENTO = {"VDE": "Débito / transferencia", "VCR": "Crédito", "VEF": "Efectivo", "VCH": "Cheque",
                      "VBB": "Bienes", "VSR": "Servicios", "VTC": "Tarjeta de crédito",
                      "VFC": "Financiamiento o crédito", "VCV": "Título valor / contrato"}
FORMAS_PAGO_SRI = {"01": "Sin utilización del sistema financiero", "15": "Compensación de deudas",
                   "16": "Tarjeta de débito", "17": "Dinero electrónico", "18": "Tarjeta prepago",
                   "19": "Tarjeta de crédito", "20": "Otros con utilización del sistema financiero",
                   "21": "Endoso de títulos"}
# Forma de pago del SRI -> instrumento monetario de la UAFE. El 20 (transferencias, cheques…) lo elige
# el usuario, porque la factura no dice cuál fue.
INSTRUMENTO_POR_FORMA = {"01": "VEF", "16": "VDE", "17": "VDE", "18": "VDE", "19": "VTC", "21": "VCV"}


@dataclass
class Opciones:
    ttr: str = "103"          # tipo de transacción
    ttb: str = "OFI"          # tipo de bien
    adb: str = "0"            # área del bien
    instrumento_20: str = "VDE"  # cómo registrar la forma de pago 20 / desconocida
    aec: str = ""             # actividad económica para clientes que no se conocen
    ccc: str = "1701"         # cantón para clientes sin dirección reconocible
    nac: str = "ECU"          # nacionalidad por defecto

    def a_dict(self) -> dict:
        return dict(self.__dict__)


@dataclass
class Propuesta:
    archivo: str
    estado: str
    factura: Factura | None = None
    observaciones: list[str] = field(default_factory=list)
    incluir: bool = True
    ttr: str = ""
    instrumento: str = ""          # instrumento principal (si la factura tiene una sola forma de pago)
    instrumento_fijo: bool = False  # el usuario lo eligió: todo el valor va a ese instrumento
    ttb: str = ""
    adb: str = ""
    cco: str = ""
    cliente: dict[str, str] = field(default_factory=dict)

    @property
    def texto(self) -> str:
        return " · ".join(self.observaciones)


# ----------------------------------------------------------------------
def opciones_sugeridas(empresa: Empresa, reportes_previos: list[Reporte]) -> Opciones:
    """Lo último que usó el usuario; si no, lo más frecuente en los reportes anteriores."""
    guardadas = empresa.valores_recordados().get("_facturas") or {}
    op = Opciones()
    ttr, ttb, adb, inst = Counter(), Counter(), Counter(), Counter()
    for rep in reportes_previos:
        for ruta, reg, _anc in rep.recorrer():
            if len(ruta) == 2:
                ttb[reg.get("TTB")] += 1
                adb[reg.get("ADB")] += 1
            elif len(ruta) == 3:
                ttr[reg.get("TTR")] += 1
                for nombre in INSTRUMENTOS:
                    if (reg.get(nombre) or "0") not in ("", "0"):
                        inst[nombre] += 1
    if ttr:
        op.ttr = ttr.most_common(1)[0][0] or op.ttr
    if ttb:
        op.ttb = ttb.most_common(1)[0][0] or op.ttb
    if adb:
        op.adb = adb.most_common(1)[0][0] or op.adb
    aec, ccc = Counter(), Counter()
    for rep in reportes_previos:
        for c in rep.clientes:
            aec[c.get("AEC")] += 1
            ccc[c.get("CCC")] += 1
    aec.pop("", None)
    ccc.pop("", None)
    if aec:
        op.aec = aec.most_common(1)[0][0]
    if ccc:
        op.ccc = ccc.most_common(1)[0][0]
    if inst:
        op.instrumento_20 = inst.most_common(1)[0][0]
    for k, v in guardadas.items():  # lo último que eligió el usuario manda
        if k in op.__dict__ and v:
            setattr(op, k, v)
    return op


# ----------------------------------------------------------------------
# Datos del RESU por factura
#   Cada factura es una operación (tipo de bien, área, cantón) con una transacción (tipo de
#   transacción e instrumento de pago). El valor de cada campo sale, en este orden, de:
#     1. lo que el usuario eligió para esa factura (Factura.resu),
#     2. la forma de pago de la factura (solo el instrumento, si no es la 20),
#     3. la última operación de ese mismo cliente en un reporte anterior,
#     4. el valor por defecto.
CAMPOS_FACTURA = ("ttr", "inst", "ttb", "adb", "cco")
FACTURA, PAGO, ANTERIOR, DEFECTO, CLIENTE, VARIOS = "factura", "pago", "anterior", "defecto", "cliente", "varios"


def ultimos_por_cliente(reportes: list[Reporte], antes_de: str = "") -> dict[str, dict[str, str]]:
    """Último tipo de transacción, instrumento, tipo de bien, área y cantón usados con cada cliente.

    Solo reportes de periodos anteriores a `antes_de` (AAAAMMDD), del más viejo al más nuevo."""
    salida: dict[str, dict[str, str]] = {}
    for rep in sorted(reportes, key=lambda r: r.periodo):
        if antes_de and rep.periodo >= antes_de:
            continue
        for c in rep.clientes:
            ide = c.get("IDE")
            if not ide:
                continue
            for op in c.hijos:
                d = {"ttb": op.get("TTB"), "adb": op.get("ADB"), "cco": op.get("CCO"), "_periodo": rep.periodo}
                for t in op.hijos:
                    d["ttr"] = t.get("TTR")
                    usados = [n for n in INSTRUMENTOS if (t.get(n) or "0") not in ("", "0")]
                    if len(usados) == 1:
                        d["inst"] = usados[0]
                salida[ide] = {k: v for k, v in d.items() if v}
    return salida


def valores_factura(f: Factura, opciones: Opciones, anteriores: dict[str, dict[str, str]] | None = None,
                    canton_cliente: str = "") -> dict[str, tuple[str, str]]:
    """campo -> (valor, origen) para los datos del RESU de una factura."""
    previo = (anteriores or {}).get(f.id_cliente, {})
    elegido = f.resu or {}
    defecto = {"ttr": opciones.ttr, "inst": opciones.instrumento_20, "ttb": opciones.ttb, "adb": opciones.adb,
               "cco": canton_cliente or opciones.ccc}
    salida: dict[str, tuple[str, str]] = {}
    for campo in CAMPOS_FACTURA:
        if elegido.get(campo):
            salida[campo] = (elegido[campo], FACTURA)
            continue
        if campo == "inst":
            formas = [c for c, v in f.pagos if v > 0] or [c for c, _v in f.pagos]
            if len(formas) > 1:
                salida[campo] = ("", VARIOS)  # se reparte según las formas de pago
                continue
            if formas and formas[0] in INSTRUMENTO_POR_FORMA:
                salida[campo] = (INSTRUMENTO_POR_FORMA[formas[0]], PAGO)
                continue
        if previo.get(campo):
            salida[campo] = (previo[campo], ANTERIOR)
        elif campo == "cco" and canton_cliente:
            salida[campo] = (canton_cliente, CLIENTE)
        else:
            salida[campo] = (defecto[campo], DEFECTO)
    return salida


def canton_por_direccion(direccion: str, cantones: dict[str, str]) -> str:
    """Busca el nombre de un cantón dentro de la dirección ('PICHINCHA / QUITO / …' -> 1701).

    Una calle puede llamarse como un cantón: si coinciden varios, vale el que además tenga su provincia en la
    dirección; si sigue la duda, devuelve "" (mejor el valor por defecto, en gris, que un cantón inventado)."""
    def plano(t: str) -> str:
        return re.sub(r"[^A-Z0-9]+", " ", sin_tildes(t.upper())).strip()

    texto = f" {plano(direccion)} "
    hallados = {codigo: n for codigo, n in ((c, plano(v)) for c, v in cantones.items())
                if codigo != "0000" and len(n) >= 4 and f" {n} " in texto}
    # «SAN MIGUEL DE LOS BANCOS» no cuenta también como «SAN MIGUEL»
    hallados = {c: n for c, n in hallados.items()
                if not any(n != m and f" {n} " in f" {m} " for m in hallados.values())}
    if len(hallados) > 1:
        def con_provincia(codigo: str, nombre: str) -> bool:
            provincia = plano(PROVINCIAS.get(codigo[:2], ""))
            veces = len(re.findall(rf"(?= {provincia} )", texto)) if provincia else 0
            return veces > (provincia == nombre)     # «LOJA»: el cantón no sirve de prueba de su propia provincia

        hallados = {c: n for c, n in hallados.items() if con_provincia(c, n)}
    return next(iter(hallados)) if len(hallados) == 1 else ""


def _datos_cliente(f: Factura, empresa: Empresa, rep: Reporte) -> tuple[dict[str, str], list[str]]:
    """Valores del cliente: los del reporte o del directorio, completados con la factura."""
    notas: list[str] = []
    existente = next((c for c in rep.clientes if c.get("IDE") == f.id_cliente), None)
    v = dict(existente.valores) if existente else dict(empresa.directorio_clientes().get(f.id_cliente, {}))
    nuevo = not v
    v.setdefault("TID", TIPO_ID.get(f.tipo_id_cliente, ""))
    v["IDE"] = f.id_cliente
    if not v.get("NRS"):
        v["NRS"] = " ".join(f.nombre_cliente.upper().split())
    if not v.get("DIR") and f.direccion_cliente:
        v["DIR"] = " ".join(f.direccion_cliente.upper().split())
    if not v.get("CCC") and v.get("DIR"):
        codigo = canton_por_direccion(v["DIR"], empresa.catalogos.tabla("C"))
        if codigo:
            v["CCC"] = codigo
            notas.append(f"Cantón tomado de la dirección: {empresa.catalogos.nombre('C', codigo)} (revíselo)")
    if not v.get("NAC") and v.get("TID") in ("R", "C"):
        v["NAC"] = "ECU"
    if not v.get("IMT"):
        v["IMT"] = "0"
    faltan = [nombre for campo, nombre in (("AEC", "actividad económica"), ("DIR", "dirección"),
                                           ("CCC", "cantón"), ("NAC", "nacionalidad")) if not v.get(campo)]
    if faltan:
        notas.append(f"{'Cliente nuevo: f' if nuevo else 'F'}alta {', '.join(faltan)} (complételo en Clientes; "
                     "se recordará para los próximos meses)")
    return v, notas


def analizar(leidos: list[Factura | NoLeido], empresa: Empresa, rep: Reporte, opciones: Opciones,
             anteriores: dict[str, dict[str, str]] | None = None) -> list[Propuesta]:
    propuestas: list[Propuesta] = []
    vistos: set[str] = set()
    ya_en_reporte = {(c.get("IDE"), t.get("NFA")) for c in rep.clientes for o in c.hijos for t in o.hijos}
    for item in leidos:
        if isinstance(item, NoLeido):
            propuestas.append(Propuesta(item.archivo, OMITIR, observaciones=[item.motivo], incluir=False))
            continue
        f = item
        p = Propuesta(f.archivo, LISTA, f, ttr=opciones.ttr)
        propuestas.append(p)

        def omitir(motivo: str) -> None:
            p.estado, p.incluir = OMITIR, False
            p.observaciones.append(motivo)

        if f.tipo != "01":
            omitir(f"{f.tipo_nombre}: solo se importan facturas"
                   + (" (si fue devolución de valores, regístrela como transacción 98)" if f.tipo == "04" else ""))
            continue
        if empresa.ruc and f.ruc_emisor and f.ruc_emisor != empresa.ruc:
            omitir(f"No la emitió {empresa.nombre} (RUC emisor {f.ruc_emisor}): ¿es una compra?")
            continue
        if f.origen != "excel" and (f.fecha is None or f.fecha.strftime("%Y%m") != rep.periodo[:6]):
            fecha = f.fecha.strftime("%d/%m/%Y") if f.fecha else "sin fecha"
            omitir(f"Es de otro mes ({fecha}); el reporte es de {rep.periodo[4:6]}/{rep.periodo[:4]}")
            continue
        if f.tipo_id_cliente == "07" or f.id_cliente == "9999999999999":
            omitir("Consumidor final: el RESU necesita la identificación del cliente")
            continue
        if not f.id_cliente:
            omitir("No se encontró la identificación del cliente")
            continue
        clave = f.clave_acceso or f"{f.ruc_emisor}|{f.id_cliente}|{f.numero}"
        if clave in vistos:
            omitir("Repetida en esta selección")
            continue
        vistos.add(clave)
        if f.origen != "excel" and (f.id_cliente, f.numero) in ya_en_reporte:
            omitir("Ya está en el reporte")
            continue
        if int(f.total) < 1:
            omitir("Valor total menor a 1 dólar")
            continue
        p.cliente, notas = _datos_cliente(f, empresa, rep)
        p.observaciones += notas
        v = valores_factura(f, opciones, anteriores, p.cliente.get("CCC", ""))
        p.ttr = v["ttr"][0]
        p.ttb, p.adb = v["ttb"][0], v["adb"][0]
        p.cco = v["cco"][0] if v["cco"][1] != CLIENTE else ""   # vacío: el del cliente
        inst, origen = v["inst"]
        p.instrumento = inst or opciones.instrumento_20
        p.instrumento_fijo = origen == FACTURA  # elegido a mano: todo el valor va a ese instrumento
        formas = [c for c, _v in f.pagos]
        if not formas and f.origen != "txt" and origen == DEFECTO:
            p.observaciones.append("La factura no indica la forma de pago: se usa la elegida arriba")
        revisar(p, opciones)
    return propuestas


def revisar(p: Propuesta, opciones: Opciones) -> None:
    """Recalcula el estado según el tipo de transacción e instrumento elegidos."""
    if p.estado == OMITIR or p.factura is None:
        return
    p.observaciones = [o for o in p.observaciones if not o.startswith("El tipo de transacción")]
    permitidos = INSTRUMENTOS_POR_TRANSACCION.get(p.ttr)
    usados = {nombre for nombre, valor in instrumentos(p, opciones).items() if valor}
    if permitidos is not None and usados - permitidos:
        nombres = ", ".join(NOMBRE_INSTRUMENTO[u].lower() for u in sorted(usados - permitidos))
        p.observaciones.append(f"El tipo de transacción {p.ttr} no admite pago con {nombres} (tabla 2 del manual)")
    p.estado = AVISO if any(o.startswith(("Falta", "Cliente nuevo", "El tipo")) for o in p.observaciones) else LISTA


def _proporcional(montos: dict[str, int], total: int) -> dict[str, int]:
    """Reparte `total` en la misma proporción (enteros, nunca negativos); lo que sobra va al mayor."""
    suma = sum(montos.values())
    if not suma:
        return montos
    nuevos = {k: v * total // suma for k, v in montos.items()}
    nuevos[max(nuevos, key=nuevos.get)] += total - sum(nuevos.values())
    return nuevos


def instrumentos(p: Propuesta, opciones: Opciones) -> dict[str, int]:
    """Valor entero en cada instrumento monetario; la suma es igual al total truncado de la factura."""
    f = p.factura
    total = int(f.total)
    valores = dict.fromkeys(INSTRUMENTOS, 0)
    pagos = [(c, v) for c, v in f.pagos if v > 0]
    if len(pagos) <= 1 or p.instrumento_fijo:
        valores[p.instrumento or opciones.instrumento_20] = total
        return valores
    for codigo, valor in pagos:
        destino = INSTRUMENTO_POR_FORMA.get(codigo, opciones.instrumento_20)
        valores[destino] += int(valor)
    return _proporcional(valores, total)       # cuadra los centavos truncados y un total editado a mano


def aplicar(rep: Reporte, propuestas: list[Propuesta], empresa: Empresa, opciones: Opciones,
            recordar_clientes: bool = True) -> int:
    """Agrega al reporte las propuestas marcadas. Devuelve cuántas facturas se agregaron."""
    agregadas = 0
    for p in propuestas:
        if not p.incluir or p.estado == OMITIR or p.factura is None:
            continue
        f = p.factura
        cliente = next((c for c in rep.clientes if c.get("IDE") == f.id_cliente), None)
        if cliente is None:
            cliente = Registro(dict(p.cliente))
            rep.clientes.append(cliente)
        else:
            for k, v in p.cliente.items():
                if v and not cliente.get(k):
                    cliente.valores[k] = v
        if f.original:
            cliente.hijos.append(operacion_desde_original(p))
            agregadas += 1
            continue
        fecha = f.fecha.strftime("%Y%m%d")
        total = str(int(f.total))
        operacion = Registro({"NCT": f.numero, "VTO": total, "FDO": fecha, "TTB": p.ttb or opciones.ttb,
                              "ADB": p.adb or opciones.adb, "DRB": cliente.get("DIR"),
                              "CCO": p.cco or cliente.get("CCC"), "PUB": "EC"})
        valores = {k: str(v) for k, v in instrumentos(p, opciones).items()}
        operacion.hijos.append(Registro({
            "FTR": fecha, "NFA": f.numero, **valores, "VVT": total, "MND": "USD", "CAT": empresa.agencia_defecto(),
            "TTR": p.ttr, "RPT": "0", "TIT": "0", "IDT": "0", "NRT": "0"}))
        cliente.hijos.append(operacion)
        agregadas += 1
    empresa.recordar_valores("_facturas", opciones.a_dict())
    if recordar_clientes:
        empresa.recordar_clientes([c.valores for c in rep.clientes])
    return agregadas


# ----------------------------------------------------------------------
# Modo simple: el reporte se arma completo desde la lista de facturas, con valores por defecto
# para lo que las facturas no traen (sin pedir nada al usuario).
def completar_por_defecto(cliente: dict[str, str], empresa: Empresa, opciones: Opciones) -> list[str]:
    """Llena lo que falta del cliente con los valores por defecto. Devuelve qué se completó."""
    puestos = []
    cat = empresa.catalogos
    if not cliente.get("AEC") and opciones.aec:
        cliente["AEC"] = opciones.aec
        puestos.append("actividad económica")
    if not cliente.get("CCC"):
        cliente["CCC"] = opciones.ccc
        puestos.append("cantón")
    if not cliente.get("NAC"):
        cliente["NAC"] = opciones.nac
    if not cliente.get("IMT"):
        cliente["IMT"] = "0"
    direccion = cliente.get("DIR", "")
    if len(direccion) < 8:  # el manual pide mínimo 8 caracteres
        base = direccion or cat.nombre("C", cliente.get("CCC", "")) or "SIN DIRECCION"
        cliente["DIR"] = f"{base} - ECUADOR"
        puestos.append("dirección")
    return puestos


def construir_reporte(empresa: Empresa, anio: int, mes: int, lista: list[Factura],
                      opciones: Opciones, anteriores: dict[str, dict[str, str]] | None = None
                      ) -> tuple[Reporte, list[Propuesta]]:
    """Reporte RESU completo a partir de las facturas del mes (con los datos elegidos por factura)."""
    rep = Reporte(empresa.codigo, anio, mes)
    propuestas = analizar(list(lista), empresa, rep, opciones, anteriores)
    for p in propuestas:
        if p.estado != OMITIR:
            p.observaciones = []
            completar_por_defecto(p.cliente, empresa, opciones)
            p.incluir = True
    # no se guardan en el directorio: los valores por defecto no son datos propios del cliente
    aplicar(rep, propuestas, empresa, opciones, recordar_clientes=False)
    for cliente in rep.clientes:  # las operaciones toman la dirección y el cantón del cliente
        for op in cliente.hijos:
            op.valores["DRB"] = op.get("DRB") or cliente.get("DIR")
            op.valores["CCO"] = op.get("CCO") or cliente.get("CCC")
    return rep, propuestas


# ----------------------------------------------------------------------
# Plantillas CLI / OPR / TRA -> filas de la tabla (una por operación)
TIPO_ID_SRI = {v: k for k, v in TIPO_ID.items()}   # R -> 04, C -> 05…


def _instrumento_unico(t: Registro) -> str:
    usados = [n for n in INSTRUMENTOS if (t.get(n) or "0") not in ("", "0")]
    return usados[0] if len(usados) == 1 else ""


def facturas_desde_reporte(rep: Reporte) -> list[Factura]:
    """Cada operación del reporte como una fila; lo que trae queda como elegido para esa fila."""
    import datetime as dt

    salida: list[Factura] = []
    for c in rep.clientes:
        for op in c.hijos:
            nct = op.get("NCT")
            m = re.fullmatch(r"(\d{3})-(\d{3})-(\d{1,9})", nct)
            f = Factura(f"Plantillas {rep.periodo[4:6]}/{rep.periodo[:4]}", origen="excel",
                        tipo_id_cliente=TIPO_ID_SRI.get(c.get("TID"), ""), id_cliente=c.get("IDE"),
                        nombre_cliente=c.get("NRS"), direccion_cliente=c.get("DIR"),
                        estab=m.group(1) if m else "", pto_emi=m.group(2) if m else "",
                        secuencial=m.group(3) if m else nct)
            fecha = op.get("FDO") or (op.hijos[0].get("FTR") if op.hijos else "")
            try:
                f.fecha = dt.date(int(fecha[:4]), int(fecha[4:6]), int(fecha[6:8]))
            except (ValueError, IndexError):
                f.fecha = None
            vto = op.get("VTO")
            f.total = Decimal(vto if vto.isdigit() else "0")
            f.resu = {"ttb": op.get("TTB"), "adb": op.get("ADB"), "cco": op.get("CCO")}
            ttrs = {t.get("TTR") for t in op.hijos}
            if len(ttrs) == 1:
                f.resu["ttr"] = next(iter(ttrs))
            if len(op.hijos) == 1 and _instrumento_unico(op.hijos[0]):
                f.resu["inst"] = _instrumento_unico(op.hijos[0])
            f.resu = {k: v for k, v in f.resu.items() if v}
            f.original = {"op": dict(op.valores), "trs": [dict(t.valores) for t in op.hijos],
                          "resu": dict(f.resu)}
            salida.append(f)
    return salida


def operacion_desde_original(p: Propuesta) -> Registro:
    """Rehace la operación importada; solo cambia lo que el usuario cambió en la tabla."""
    f = p.factura
    orig = f.original
    antes = orig.get("resu", {})
    op = Registro(dict(orig["op"]))
    for campo, clave in (("ttb", "TTB"), ("adb", "ADB"), ("cco", "CCO")):
        valor = getattr(p, campo)
        if valor and valor != antes.get(campo):
            op.valores[clave] = valor
    total = str(int(f.total))
    total_cambiado = total != (orig["op"].get("VTO") or "")
    if total_cambiado:
        op.valores["VTO"] = total
    for t in orig["trs"]:
        tr = Registro(dict(t))
        if p.ttr and p.ttr != antes.get("ttr"):
            tr.valores["TTR"] = p.ttr
        if len(orig["trs"]) == 1 and not _instrumento_unico(tr) and not p.instrumento_fijo:
            if total_cambiado:                        # pago repartido: se conserva la proporción
                montos = {n: int(tr.get(n)) if tr.get(n).isdigit() else 0 for n in INSTRUMENTOS}
                tr.valores.update({k: str(v) for k, v in _proporcional(montos, int(total)).items()})
                tr.valores["VVT"] = total
        elif len(orig["trs"]) == 1:
            inst = p.instrumento if p.instrumento and p.instrumento != antes.get("inst") else \
                (_instrumento_unico(tr) or p.instrumento)
            if total_cambiado or inst != _instrumento_unico(tr):
                valor = total if total_cambiado else (tr.get("VVT") or
                                                      str(sum(int(tr.get(n) or "0") for n in INSTRUMENTOS)))
                for n in INSTRUMENTOS:
                    tr.valores[n] = "0"
                tr.valores[inst] = valor
                tr.valores["VVT"] = valor
        op.hijos.append(tr)
    return op
