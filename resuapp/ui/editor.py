"""Ventana para agregar o editar un cliente, una operación o una transacción."""

from __future__ import annotations

from PySide6.QtCore import QDate, Qt, QTimer
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QGridLayout, QLabel, QScrollArea, QVBoxLayout,
                               QWidget)

from ..empresas import Empresa
from ..estructura import Archivo
from ..modelo import INSTRUMENTOS, Registro, Reporte, calcular_total
from ..reglas import INSTRUMENTOS_POR_TRANSACCION, Validador
from .campos import Control, ControlFecha, crear_control

AYUDAS = {
    "TID": "C cédula, R RUC, P pasaporte, A análogo.",
    "IDE": "Al escribir una identificación ya usada, se completan sus datos.",
    "NRS": "Nombres completos o razón social completa, sin abreviaturas.",
    "IMT": "Personas naturales: ingreso mensual. Sociedades: ventas anuales. 0 si no se conoce.",
    "DIR": "Calle principal, numeración y calle transversal (mínimo 8 caracteres).",
    "NCT": "Número del contrato. Para sub-operaciones del mismo acto use guion: 100-1.",
    "VTO": "Costo total del bien o del contrato.",
    "ADB": "Área del inmueble; 0 si no se conoce.",
    "CCO": "0000 si el bien está en el extranjero.",
    "FTR": "Debe ser del mes que se reporta.",
    "NFA": "Número de factura, documento o comprobante.",
    "VVT": "Se calcula solo: suma de los instrumentos monetarios.",
    "CAT": "Código de agencia: código de la empresa + código de la oficina (8 o 9 dígitos).",
    "RPT": "0 no aplica, 1 propios, 2 de terceros, 3 mixto. Con 2 o 3 se piden los datos del tercero.",
}


def etiqueta(texto: str) -> str:
    """'NOMBRES APELLIDOS RAZÓN SOCIAL' -> 'Nombres apellidos razón social'."""
    t = texto.strip().capitalize()
    for sigla in (" o ", " / "):
        t = t.replace(sigla.upper(), sigla)
    return t


class DialogoRegistro(QDialog):
    def __init__(self, empresa: Empresa, reporte: Reporte, nivel: Archivo, registro: Registro,
                 ancestros: list[Registro], ruta: tuple, titulo: str, parent=None):
        super().__init__(parent)
        self.empresa, self.reporte, self.nivel = empresa, reporte, nivel
        self.est, self.cat = empresa.estructura, empresa.catalogos
        self.ancestros, self.ruta = ancestros, ruta
        self.setWindowTitle(titulo)
        self.setSizeGripEnabled(True)
        self.resize(940 if len(nivel.propios) > 10 else 620, 640)

        contexto = QLabel(self._contexto())
        contexto.setWordWrap(True)
        contexto.setStyleSheet("color: palette(mid); padding-bottom: 4px;")

        self.controles: dict[str, Control] = {}
        rejilla = QGridLayout()
        rejilla.setHorizontalSpacing(14)
        visibles = [c for c in nivel.propios if c.nombre not in ("CDR", "FCT")]
        columnas = 2 if len(visibles) > 10 else 1
        filas_por_col = -(-len(visibles) // columnas)
        corte = QDate.fromString(reporte.periodo, "yyyyMMdd")
        for i, campo in enumerate(visibles):
            control = crear_control(campo, self.cat)
            if isinstance(control, ControlFecha):
                control.proponer(corte)
            control.poner_valor(registro.get(campo.nombre))
            control.setToolTip(AYUDAS.get(campo.nombre, ""))
            control.cambiado.connect(self._programar_revision)
            self.controles[campo.nombre] = control
            nombre = QLabel(etiqueta(campo.etiqueta) + ":")
            nombre.setToolTip(AYUDAS.get(campo.nombre, ""))
            fila, col = i % filas_por_col, (i // filas_por_col) * 2
            rejilla.addWidget(nombre, fila, col, Qt.AlignRight)
            rejilla.addWidget(control, fila, col + 1)
        for col in range(columnas):
            rejilla.setColumnStretch(col * 2 + 1, 1)
        rejilla.setRowStretch(filas_por_col, 1)
        cuerpo = QWidget()
        cuerpo.setLayout(rejilla)
        desplazable = QScrollArea()
        desplazable.setWidgetResizable(True)
        desplazable.setWidget(cuerpo)

        self.aviso = QLabel()
        self.aviso.setWordWrap(True)
        self.aviso.setTextFormat(Qt.RichText)
        self.aviso.setMinimumHeight(40)
        botones = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        botones.button(QDialogButtonBox.Ok).setText("Guardar")
        botones.button(QDialogButtonBox.Cancel).setText("Cancelar")
        botones.accepted.connect(self.accept)
        botones.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addWidget(contexto)
        lay.addWidget(desplazable, 1)
        lay.addWidget(self.aviso)
        lay.addWidget(botones)

        self._temporizador = QTimer(self, singleShot=True, interval=250, timeout=self._revisar)
        if "IDE" in self.controles and nivel.nombre == "CLIENTE":
            self.controles["IDE"].edit.editingFinished.connect(self._buscar_cliente)
        self._revisar()

    # ------------------------------------------------------------------
    def _contexto(self) -> str:
        partes = [f"Empresa: {self.empresa.nombre} · Código {self.reporte.codigo} · Corte "
                  f"{self.reporte.periodo[6:]}/{self.reporte.periodo[4:6]}/{self.reporte.periodo[:4]}"]
        for anc, nivel in zip(self.ancestros, self.est.niveles):
            if nivel.nombre == "CLIENTE":
                partes.append(f"Cliente: {anc.get('IDE')} {anc.get('NRS')}")
            elif nivel.nombre == "OPERACION":
                partes.append(f"Operación: {anc.get('NCT')}")
        return "  ·  ".join(partes)

    def valores(self) -> dict[str, str]:
        v = {nombre: c.valor() for nombre, c in self.controles.items()}
        calcular_total(self.est, self.nivel, v)
        return v

    def _programar_revision(self) -> None:
        self._temporizador.start()

    def _revisar(self) -> None:
        inmobiliaria = self.est.es_inmobiliaria and self.nivel.nombre == "TRANSACCION"
        if inmobiliaria:
            self._ajustar_transaccion()
        v = self.valores()
        if "VVT" in self.controles and inmobiliaria:
            self.controles["VVT"].poner_valor(v["VVT"])
        completos = self.reporte.valores_completos(self.nivel, Registro(v), self.ancestros)
        mensajes = Validador(self.est, self.cat).validar_registro(self.reporte, self.ruta, self.nivel, completos)
        for nombre, control in self.controles.items():
            con_error = any(m.campo == nombre and m.es_error for m in mensajes)
            control.setStyleSheet("QLineEdit, QComboBox, QDateEdit { border: 1px solid #c62828; }"
                                  if con_error else "")
        if not mensajes:
            self.aviso.setText("<span style='color:#2e7d32'>✔ Datos completos y correctos.</span>")
            return
        lineas = [f"<span style='color:{'#c62828' if m.es_error else '#b26a00'}'>• {m.texto}</span>"
                  for m in mensajes[:6]]
        if len(mensajes) > 6:
            lineas.append(f"… y {len(mensajes) - 6} más.")
        self.aviso.setText("<br>".join(lineas))

    def _ajustar_transaccion(self) -> None:
        """Habilita solo los instrumentos permitidos por el tipo de transacción y los datos del tercero
        cuando los recursos son de terceros o mixtos."""
        vvt = self.controles.get("VVT")
        if vvt is not None:
            vvt.setEnabled(False)
        ttr = self.controles.get("TTR")
        permitidos = INSTRUMENTOS_POR_TRANSACCION.get(ttr.valor()) if ttr else None
        for nombre in INSTRUMENTOS:
            control = self.controles.get(nombre)
            if control is None:
                continue
            habilitado = permitidos is None or nombre in permitidos
            if not habilitado and control.valor() not in ("", "0"):
                habilitado = True  # que se vea el valor que hay que corregir
            control.setEnabled(habilitado)
            if control.valor() == "":
                control.poner_valor("0")
        rpt = self.controles.get("RPT")
        con_tercero = rpt is not None and rpt.valor() in ("2", "3")
        for nombre in ("TIT", "IDT", "NRT"):
            control = self.controles.get(nombre)
            if control is None:
                continue
            control.setEnabled(con_tercero)
            if not con_tercero and control.valor() != "0":
                control.poner_valor("0")
            elif con_tercero and control.valor() == "0":
                control.poner_valor("")

    def _buscar_cliente(self) -> None:
        """Si la identificación ya está en el directorio de la empresa, completa los demás datos vacíos."""
        ide = self.controles["IDE"].valor()
        datos = self.empresa.directorio_clientes().get(ide)
        if not datos:
            return
        for nombre, control in self.controles.items():
            if nombre != "IDE" and not control.valor() and datos.get(nombre):
                control.poner_valor(datos[nombre])
        self._revisar()
