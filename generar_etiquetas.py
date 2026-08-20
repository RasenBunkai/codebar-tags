#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Generador de etiquetas para inventario.

Formato del identificador:
    NUMERO_DE_SERIE-CONSECUTIVO

Ejemplos:
    PF306BAC-001
    T6NXLP00W46323C-002

Características:
- Hoja personalizada: 220 x 152 mm
- Etiquetas: 63 x 32 mm
- 3 columnas x 4 filas = 12 etiquetas por hoja
- Separación: 6 mm horizontal y vertical
- Código de barras Code 128 real
- Consecutivo automático de 3 dígitos

Instalación:
    py -m pip install reportlab

Uso:
    py generar_etiquetas.py seriales.txt

Generar con guías:
    py generar_etiquetas.py seriales.txt --guias

Empezar el consecutivo desde otro número:
    py generar_etiquetas.py seriales.txt --inicio 25

Archivo de salida personalizado:
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
ETIQUETAS_POR_HOJA = COLS * ROWS

# Vertical:
# 3 + (4 × 32) + (3 × 6) + 3 = 152 mm
TOP_MARGIN = 3 * mm

# Horizontal:
# (3 × 63) + (2 × 6) = 201 mm
# 220 - 201 = 19 mm
# Centrado = 9.5 mm por lado
GRID_W = COLS * LABEL_W + (COLS - 1) * GAP_X
GRID_LEFT = (PAGE_W - GRID_W) / 2


# ---------------------------------------------------------------------
# DISEÑO DEL CÓDIGO DE BARRAS
# ---------------------------------------------------------------------

# Se usa 0.22 mm para permitir identificadores largos
# como T6NXLP00W46323C-001 dentro de 63 mm.
BAR_WIDTH = 0.22 * mm
BAR_HEIGHT = 14 * mm

# Zona silenciosa mínima a ambos lados
BAR_QUIET = 10 * BAR_WIDTH

SERIAL_SIZE_SHORT = 10
SERIAL_SIZE_LONG = 8
CONSECUTIVO_MINIMO = 1
CONSECUTIVO_MAXIMO = 999


# ---------------------------------------------------------------------
# LECTURA DE SERIALES
# ---------------------------------------------------------------------

def leer_seriales(ruta: Path) -> list[str]:

    if not ruta.exists():
        raise FileNotFoundError(
            f"No existe el archivo: {ruta}"
        )

    seriales = []
    vistos = set()

    lineas = ruta.read_text(
        encoding="utf-8-sig"
    ).splitlines()

    for num_linea, linea in enumerate(lineas, start=1):

        serial = linea.strip()

        if not serial:
            continue

        # Evitar espacios accidentales
        if any(ch.isspace() for ch in serial):

            raise ValueError(
                f"Linea {num_linea}: "
                f"el numero de serie contiene espacios: {serial!r}"
            )

        # Evitar duplicados
        if serial in vistos:

            print(
                f"Advertencia: el serial {serial!r} esta repetido. "
                "Se ignorara la segunda aparicion.",
                file=sys.stderr,
            )

            continue

        vistos.add(serial)
        seriales.append(serial)

    if not seriales:
        raise ValueError(
            "El archivo no contiene numeros de serie."
        )

    return seriales


# ---------------------------------------------------------------------
# POSICIÓN DE LAS ETIQUETAS
# ---------------------------------------------------------------------

def posicion_etiqueta(
    fila: int,
    columna: int
) -> tuple[float, float]:

    """
    Devuelve la esquina inferior izquierda
    de cada etiqueta.

    Las filas se numeran visualmente
    de arriba hacia abajo.
    """

    x = (
        GRID_LEFT
        + columna * (LABEL_W + GAP_X)
    )

    y = (
        PAGE_H
        - TOP_MARGIN
        - LABEL_H
        - fila * (LABEL_H + GAP_Y)
    )

    return x, y


# ---------------------------------------------------------------------
# GUÍAS DE CALIBRACIÓN
# ---------------------------------------------------------------------

def dibujar_guias(c: canvas.Canvas):

    c.saveState()

    c.setLineWidth(0.25)
    c.setDash(1, 1)

    for fila in range(ROWS):

        for columna in range(COLS):

            x, y = posicion_etiqueta(
                fila,
                columna
            )

            c.rect(
                x,
                y,
                LABEL_W,
                LABEL_H,
                stroke=1,
                fill=0
            )

    c.restoreState()


# ---------------------------------------------------------------------
# TAMAÑO DEL TEXTO
# ---------------------------------------------------------------------

def tamano_identificador(texto: str) -> float:

    if len(texto) <= 15:
        return SERIAL_SIZE_SHORT

    return SERIAL_SIZE_LONG


# ---------------------------------------------------------------------
# IDENTIFICADORES
# ---------------------------------------------------------------------

def validar_inicio(inicio: int):

    if inicio < CONSECUTIVO_MINIMO:
        raise ValueError(
            "--inicio debe ser mayor o igual a 1."
        )

    if inicio > CONSECUTIVO_MAXIMO:
        raise ValueError(
            "--inicio no puede ser mayor a 999."
        )


def formatear_identificador(
    serial: str,
    consecutivo: int
) -> str:

    if consecutivo > CONSECUTIVO_MAXIMO:
        raise ValueError(
            "El consecutivo maximo soportado es 999. "
            "Divide el archivo en varios lotes o usa menos seriales."
        )

    return f"{serial}-{consecutivo:03d}"


def crear_registros(
    seriales: list[str],
    inicio: int
) -> list[tuple[str, int]]:

    validar_inicio(inicio)

    ultimo = inicio + len(seriales) - 1

    if ultimo > CONSECUTIVO_MAXIMO:
        raise ValueError(
            f"El lote llega hasta {ultimo:03d}, "
            "pero el consecutivo maximo soportado es 999."
        )

    return [
        (serial, inicio + indice)
        for indice, serial in enumerate(seriales)
    ]


# ---------------------------------------------------------------------
# DIBUJAR UNA ETIQUETA
# ---------------------------------------------------------------------

def dibujar_etiqueta(
    c: canvas.Canvas,
    x: float,
    y: float,
    identificador: str,
):

    # -------------------------------------------------------------
    # CODE 128
    # -------------------------------------------------------------

    barcode = Code128(
        identificador,
        barWidth=BAR_WIDTH,
        barHeight=BAR_HEIGHT,
        humanReadable=False,
        quiet=True,
        lquiet=BAR_QUIET,
        rquiet=BAR_QUIET,
    )

    # Dejamos 2 mm de seguridad en cada lado.
    max_barcode_w = LABEL_W - 4 * mm

    if barcode.width > max_barcode_w:

        raise ValueError(
            f"El codigo {identificador!r} ocupa "
            f"{barcode.width / mm:.1f} mm y excede "
            f"el ancho disponible de "
            f"{max_barcode_w / mm:.1f} mm."
        )

    # Centrar horizontalmente
    barcode_x = (
        x
        + (LABEL_W - barcode.width) / 2
    )

    # Posición vertical
    barcode_y = y + 11 * mm

    barcode.drawOn(
        c,
        barcode_x,
        barcode_y
    )

    # -------------------------------------------------------------
    # TEXTO DEL IDENTIFICADOR
    # -------------------------------------------------------------

    c.setFont(
        "Helvetica-Bold",
        tamano_identificador(identificador)
    )

    c.drawCentredString(
        x + LABEL_W / 2,
        y + 5.5 * mm,
        identificador,
    )


# ---------------------------------------------------------------------
# DIBUJAR UNA PÁGINA
# ---------------------------------------------------------------------

def dibujar_pagina(
    c: canvas.Canvas,
    grupo: list[tuple[str, int]],
    guias: bool
):

    if guias:
        dibujar_guias(c)

    for posicion, (serial, consecutivo) in enumerate(grupo):

        fila = posicion // COLS
        columna = posicion % COLS

        x, y = posicion_etiqueta(
            fila,
            columna
        )

        identificador = formatear_identificador(
            serial,
            consecutivo
        )

        dibujar_etiqueta(
            c,
            x,
            y,
            identificador
        )


# ---------------------------------------------------------------------
# GENERAR PDF
# ---------------------------------------------------------------------

def generar_pdf(
    seriales: list[str],
    salida: Path,
    inicio: int = 1,
    guias: bool = False
):

    salida.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    c = canvas.Canvas(
        str(salida),
        pagesize=(PAGE_W, PAGE_H)
    )

    c.setTitle(
        "Etiquetas de inventario Code 128"
    )

    registros = crear_registros(
        seriales,
        inicio
    )

    for inicio_pagina in range(
        0,
        len(registros),
        ETIQUETAS_POR_HOJA
    ):

        grupo = registros[
            inicio_pagina:
            inicio_pagina + ETIQUETAS_POR_HOJA
        ]

        dibujar_pagina(
            c,
            grupo,
            guias
        )

        c.showPage()

    c.save()


# ---------------------------------------------------------------------
# PROGRAMA PRINCIPAL
# ---------------------------------------------------------------------

def main():

    parser = argparse.ArgumentParser(
        description=(
            "Genera etiquetas Code 128 "
            "con numero de serie y consecutivo."
        )
    )

    parser.add_argument(
        "archivo",
        nargs="?",
        default="seriales.txt",
        help=(
            "TXT con un numero de serie por linea "
            "(default: seriales.txt)"
        ),
    )

    parser.add_argument(
        "-o",
        "--salida",
        default="etiquetas.pdf",
        help=(
            "Nombre del PDF de salida "
            "(default: etiquetas.pdf)"
        ),
    )

    parser.add_argument(
        "--inicio",
        type=int,
        default=1,
        help=(
            "Numero inicial del consecutivo "
            "(default: 1)"
        ),
    )

    parser.add_argument(
        "--guias",
        action="store_true",
        help=(
            "Dibuja el contorno de las "
            "12 etiquetas para calibracion."
        ),
    )

    args = parser.parse_args()

    entrada = Path(args.archivo)
    salida = Path(args.salida)

    try:

        seriales = leer_seriales(
            entrada
        )

        generar_pdf(
            seriales,
            salida,
            inicio=args.inicio,
            guias=args.guias
        )

    except Exception as exc:

        print(
            f"ERROR: {exc}",
            file=sys.stderr
        )

        return 1

    paginas = (
        len(seriales) + 11
    ) // 12

    ultimo = (
        args.inicio
        + len(seriales)
        - 1
    )

    print()
    print(
        f"PDF generado: {salida.resolve()}"
    )

    print(
        f"Etiquetas: {len(seriales)}"
    )

    print(
        f"Paginas: {paginas}"
    )

    print(
        f"Consecutivos: "
        f"{args.inicio:03d} - {ultimo:03d}"
    )

    print()
    print(
        "Imprime al 100 % / Tamano real, "
        "sin ajuste de pagina."
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
