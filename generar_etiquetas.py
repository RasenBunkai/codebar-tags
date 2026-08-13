#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Generador de etiquetas para inventario:
- Hoja personalizada: 220 x 152 mm
- Etiquetas: 63 x 32 mm
- 3 columnas x 4 filas = 12 etiquetas por hoja
- Separación: 6 mm horizontal y vertical
- Por cada equipo genera:
    CHROMEBOOK -> NUMERO_DE_SERIE
    CARGADOR   -> NUMERO_DE_SERIE-C
- Código de barras Code 128 real (no depende de una fuente Code_128).

Instalación:
    py -m pip install reportlab

Uso:
    py generar_etiquetas.py seriales.txt
    py generar_etiquetas.py seriales.txt --guias
    py generar_etiquetas.py seriales.txt -o etiquetas.pdf

IMPORTANTE AL IMPRIMIR:
    - Tamaño real / Actual size / 100 %
    - NO usar "Ajustar", "Fit" ni "Escalar a página"
"""

import argparse
import sys
from pathlib import Path

from reportlab.pdfgen import canvas
from reportlab.lib.units import mm
from reportlab.graphics.barcode.code128 import Code128


# ---------------------------------------------------------------------
# MEDIDAS DE LA HOJA
# ---------------------------------------------------------------------

PAGE_W = 220 * mm
PAGE_H = 152 * mm

LABEL_W = 63 * mm
LABEL_H = 32 * mm

GAP_X = 6 * mm
GAP_Y = 6 * mm

COLS = 3
ROWS = 4

# Verticalmente las medidas dadas cuadran exactamente:
# 3 + (4*32) + (3*6) + 3 = 152 mm
TOP_MARGIN = 3 * mm

# Horizontalmente:
# (3*63) + (2*6) = 201 mm
# 220 - 201 = 19 mm -> 9.5 mm por lado si centramos la cuadrícula.
#
# Tú mediste aproximadamente 8 mm por lado. Para la primera prueba
# conviene centrar la cuadrícula y, si hace falta, ajustar GRID_LEFT
# después de imprimir la hoja de prueba.
GRID_W = COLS * LABEL_W + (COLS - 1) * GAP_X
GRID_LEFT = (PAGE_W - GRID_W) / 2  # 9.5 mm


# ---------------------------------------------------------------------
# DISEÑO DE LA ETIQUETA
# ---------------------------------------------------------------------

BAR_WIDTH = 0.23 * mm       # módulo X; adecuado para estos seriales
BAR_HEIGHT = 11.5 * mm
BAR_QUIET = 10 * BAR_WIDTH  # quiet zone >= 10X a cada lado

TITLE_SIZE = 8.5
SERIAL_SIZE_SHORT = 9.5
SERIAL_SIZE_LONG = 8.0


def leer_seriales(ruta: Path) -> list[str]:
    if not ruta.exists():
        raise FileNotFoundError(f"No existe el archivo: {ruta}")

    seriales = []
    vistos = set()

    for num_linea, linea in enumerate(ruta.read_text(encoding="utf-8-sig").splitlines(), start=1):
        serial = linea.strip()

        if not serial:
            continue

        # Evitamos espacios dentro del identificador por accidente.
        if any(ch.isspace() for ch in serial):
            raise ValueError(
                f"Línea {num_linea}: el número de serie contiene espacios: {serial!r}"
            )

        # Code 128 puede representar ASCII; para inventario mantenemos
        # el valor tal como fue escrito.
        if serial in vistos:
            print(
                f"Advertencia: el serial {serial!r} aparece repetido; "
                "se generará una sola pareja de etiquetas.",
                file=sys.stderr,
            )
            continue

        vistos.add(serial)
        seriales.append(serial)

    if not seriales:
        raise ValueError("El archivo no contiene números de serie.")

    return seriales


def posicion_etiqueta(fila: int, columna: int) -> tuple[float, float]:
    """
    Devuelve la esquina inferior izquierda de una etiqueta.
    Las filas se numeran visualmente de arriba hacia abajo.
    """
    x = GRID_LEFT + columna * (LABEL_W + GAP_X)
    y = PAGE_H - TOP_MARGIN - LABEL_H - fila * (LABEL_H + GAP_Y)
    return x, y


def dibujar_guias(c: canvas.Canvas):
    """Dibuja contornos para calibrar la impresión."""
    c.saveState()
    c.setLineWidth(0.25)
    c.setDash(1, 1)

    for fila in range(ROWS):
        for columna in range(COLS):
            x, y = posicion_etiqueta(fila, columna)
            c.rect(x, y, LABEL_W, LABEL_H, stroke=1, fill=0)

    c.restoreState()


def tamano_serial(texto: str) -> float:
    return SERIAL_SIZE_SHORT if len(texto) <= 12 else SERIAL_SIZE_LONG


def dibujar_etiqueta(
    c: canvas.Canvas,
    x: float,
    y: float,
    tipo: str,
    identificador: str,
):
    # Título
    c.setFont("Helvetica-Bold", TITLE_SIZE)
    c.drawCentredString(
        x + LABEL_W / 2,
        y + LABEL_H - 5.0 * mm,
        tipo,
    )

    # Code 128 real.
    barcode = Code128(
        identificador,
        barWidth=BAR_WIDTH,
        barHeight=BAR_HEIGHT,
        humanReadable=False,
        quiet=True,
        lquiet=BAR_QUIET,
        rquiet=BAR_QUIET,
    )

    # Comprobación de seguridad para no desbordar la etiqueta.
    max_barcode_w = LABEL_W - 4 * mm
    if barcode.width > max_barcode_w:
        raise ValueError(
            f"El código {identificador!r} ocupa {barcode.width/mm:.1f} mm "
            f"y excede el ancho disponible de {max_barcode_w/mm:.1f} mm."
        )

    barcode_x = x + (LABEL_W - barcode.width) / 2
    barcode_y = y + 9.0 * mm
    barcode.drawOn(c, barcode_x, barcode_y)

    # Texto legible debajo del código.
    c.setFont("Helvetica-Bold", tamano_serial(identificador))
    c.drawCentredString(
        x + LABEL_W / 2,
        y + 4.1 * mm,
        identificador,
    )


def dibujar_pagina(c: canvas.Canvas, grupo: list[str], guias: bool):
    """
    Cada hoja admite 6 equipos = 12 etiquetas.

    Distribución:
        fila 1: Chromebook equipo 1 | Chromebook equipo 2 | Chromebook equipo 3
        fila 2: Cargador   equipo 1 | Cargador   equipo 2 | Cargador   equipo 3

        fila 3: Chromebook equipo 4 | Chromebook equipo 5 | Chromebook equipo 6
        fila 4: Cargador   equipo 4 | Cargador   equipo 5 | Cargador   equipo 6

    Así la etiqueta del cargador queda justo debajo de la de su Chromebook.
    """
    if guias:
        dibujar_guias(c)

    for i, serial in enumerate(grupo):
        bloque = 0 if i < 3 else 1
        columna = i % 3

        fila_chromebook = bloque * 2
        fila_cargador = fila_chromebook + 1

        x_ch, y_ch = posicion_etiqueta(fila_chromebook, columna)
        dibujar_etiqueta(c, x_ch, y_ch, "CHROMEBOOK", serial)

        x_ca, y_ca = posicion_etiqueta(fila_cargador, columna)
        dibujar_etiqueta(c, x_ca, y_ca, "CARGADOR", f"{serial}-C")


def generar_pdf(seriales: list[str], salida: Path, guias: bool = False):
    c = canvas.Canvas(str(salida), pagesize=(PAGE_W, PAGE_H))
    c.setTitle("Etiquetas de inventario Code 128")

    EQUIPOS_POR_HOJA = 6

    for inicio in range(0, len(seriales), EQUIPOS_POR_HOJA):
        grupo = seriales[inicio : inicio + EQUIPOS_POR_HOJA]
        dibujar_pagina(c, grupo, guias=guias)
        c.showPage()

    c.save()


def main():
    parser = argparse.ArgumentParser(
        description="Genera etiquetas Code 128 para Chromebook y cargador."
    )
    parser.add_argument(
        "archivo",
        nargs="?",
        default="seriales.txt",
        help="TXT con un número de serie por línea (default: seriales.txt)",
    )
    parser.add_argument(
        "-o",
        "--salida",
        default="etiquetas.pdf",
        help="Nombre del PDF de salida (default: etiquetas.pdf)",
    )
    parser.add_argument(
        "--guias",
        action="store_true",
        help="Dibuja el contorno de las 12 etiquetas para calibración.",
    )
    args = parser.parse_args()

    entrada = Path(args.archivo)
    salida = Path(args.salida)

    try:
        seriales = leer_seriales(entrada)
        generar_pdf(seriales, salida, guias=args.guias)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    paginas = (len(seriales) + 5) // 6
    print(f"PDF generado: {salida.resolve()}")
    print(f"Equipos: {len(seriales)}")
    print(f"Etiquetas: {len(seriales) * 2}")
    print(f"Páginas: {paginas}")
    print("Imprime al 100 % / Tamaño real, sin ajuste de página.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())