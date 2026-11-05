"""Reportes ficticios para las pruebas (identificaciones inventadas)."""

from resuapp.modelo import Registro, Reporte

CODIGO = "99999"


def cedula_ficticia(base9: str = "171111111") -> str:
    suma = 0
    for i, d in enumerate(base9):
        v = int(d) * (2 if i % 2 == 0 else 1)
        suma += v - 9 if v > 9 else v
    return base9 + str((10 - suma % 10) % 10)


def transaccion(**cambios) -> Registro:
    v = {"FTR": "20260215", "NFA": "FAC-001", "VDE": "0", "VCR": "0", "VEF": "0", "VCH": "12000", "VBB": "0",
         "VSR": "0", "VTC": "0", "VFC": "0", "VCV": "0", "VVT": "12000", "MND": "USD", "CAT": "999991000",
         "TTR": "96", "RPT": "0", "TIT": "0", "IDT": "0", "NRT": "0"}
    v.update(cambios)
    return Registro(v)


def operacion(*transacciones, **cambios) -> Registro:
    v = {"NCT": "CONTRATO-1", "VTO": "85000", "FDO": "20260210", "TTB": "DEP", "ADB": "95",
         "DRB": "AV. PRINCIPAL 123 Y SECUNDARIA", "CCO": "1701", "PUB": "EC"}
    v.update(cambios)
    return Registro(v, list(transacciones) or [transaccion()])


def cliente(*operaciones, **cambios) -> Registro:
    v = {"TID": "C", "IDE": cedula_ficticia(), "NRS": "PEREZ PRUEBA JUAN CARLOS", "AEC": "L6810", "IMT": "1500",
         "NAC": "ECU", "DIR": "CALLE FICTICIA N1-23 Y OTRA", "CCC": "1701"}
    v.update(cambios)
    return Registro(v, list(operaciones) or [operacion()])


def reporte(*clientes) -> Reporte:
    return Reporte(CODIGO, 2026, 2, list(clientes) or [cliente()])
