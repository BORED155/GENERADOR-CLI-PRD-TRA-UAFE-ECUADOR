# Generador RESU UAFE

Programa de escritorio (Linux, Windows y Mac) para preparar el **reporte RESU** de la UAFE
(SISLAFT) de una o varias empresas, sin llenar las plantillas Excel a mano.

## Cómo funciona

Una sola pantalla:

1. Elija la **empresa** (con «Empresas…» se agregan otras, cada una con su `uafi.zip`) y el **mes**.
2. **Arrastre los XML o PDF de las facturas de venta** (o carpetas, ZIP, o el TXT de comprobantes
   emitidos del portal del SRI). Si son de otro mes, el programa cambia solo al mes de las facturas.
3. Revise abajo los datos que las facturas no traen (tipo de transacción, tipo de bien, área, cómo
   registrar el pago «20», actividad económica y cantón para clientes nuevos, código de agencia). Se
   recuerdan por empresa; los clientes de reportes anteriores conservan sus propios datos.
4. **Generar Excel**: crea `CLI`, `OPR` y `TRA<código><AAAAMMDD>.xlsx` a partir de las plantillas
   oficiales (cabecera: tipo, código de registro, fecha de corte y número de registros).
5. **Abrir UAFI de la empresa**: cargue las tres plantillas, *Validar* y *Guardar* para obtener el `.uaf`.

Cada factura del mes es una operación (número = número de factura, valor = total sin decimales) con
una transacción (forma de pago del SRI → instrumento monetario de la UAFE).

## Reglas que revisa

- Las del aplicativo UAFI: longitudes, números enteros, fechas AAAAMMDD no futuras, catálogos,
  código de registro, datos del tercero según el pago (0/1 → «0»; 2/3 → obligatorios), cada cliente
  con al menos una operación y cada operación con al menos una transacción.
- Las del *Manual de generación de estructuras RESU – Inmobiliarias y Constructoras*: cédula de 10
  dígitos y RUC de 13, nombres de 5 a 150 caracteres, valor de la operación de 3 a 12 dígitos,
  transacciones solo del mes reportado, valor total = suma de instrumentos, instrumentos permitidos
  por tipo de transacción (tabla 2), código de agencia que empieza con el código de la empresa.

## Desarrollo

```bash
python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'
.venv/bin/resuapp                # interfaz
.venv/bin/python -m pytest -q    # pruebas (datos ficticios)
```

Ejecutables: `empaquetar/construir-linux.sh`, `construir-windows.bat`, `construir-mac.command`.
El UAFI oficial necesita Java instalado (Linux: `sudo apt install default-jre`).
