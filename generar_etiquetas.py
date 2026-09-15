#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import csv
import io
import os
import subprocess
import sys
import tkinter as tk
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from reportlab.graphics.barcode.code128 import Code128
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfgen import canvas

PAGE_W = 220 * mm
PAGE_H = 152 * mm
LABEL_W = 63 * mm
LABEL_H = 32 * mm
GAP_X = 6 * mm
GAP_Y = 6 * mm
COLS = 3
ROWS = 4
ETIQUETAS_POR_HOJA = COLS * ROWS
TOP_MARGIN = 3 * mm
GRID_W = COLS * LABEL_W + (COLS - 1) * GAP_X
GRID_LEFT = (PAGE_W - GRID_W) / 2

BAR_WIDTH = 0.22 * mm
BAR_HEIGHT = 14 * mm
BAR_QUIET = 10 * BAR_WIDTH
SERIAL_SIZE_SHORT = 10
SERIAL_SIZE_LONG = 8
CONSECUTIVO_MINIMO = 1
CONSECUTIVO_MAXIMO = 999

SECCIONES_DOCENTES = {
    "estancia": "Estancia",
    "preescolar": "Preescolar",
    "primaria": "Primaria",
    "secundaria": "Secundaria",
}


@dataclass(frozen=True)
class EtiquetaAlumno:
    matricula: str
    nombre: str
    grado_grupo: str
    serie: str


@dataclass(frozen=True)
class EtiquetaDocente:
    nombre: str
    seccion: str
    serie: str


def normalizar_espacios(texto: str) -> str:
    return " ".join(texto.strip().split())


def normalizar_clave(texto: str) -> str:
    texto = normalizar_espacios(texto).lower().replace("_", " ")
    texto = "".join(
        ch
        for ch in unicodedata.normalize("NFD", texto)
        if unicodedata.category(ch) != "Mn"
    )
    return texto


def normalizar_seriales(texto: str) -> list[str]:
    seriales = []
    vistos = set()

    for num_linea, linea in enumerate(texto.splitlines(), start=1):
        serial = linea.strip()

        if not serial:
            continue

        if any(ch.isspace() for ch in serial):
            raise ValueError(
                f"Línea {num_linea}: el número de serie contiene espacios: {serial!r}"
            )

        if serial in vistos:
            continue

        vistos.add(serial)
        seriales.append(serial)

    if not seriales:
        raise ValueError("No hay números de serie para generar.")

    return seriales


def validar_inicio(inicio: int):
    if inicio < CONSECUTIVO_MINIMO:
        raise ValueError("El consecutivo inicial debe ser mayor o igual a 1.")

    if inicio > CONSECUTIVO_MAXIMO:
        raise ValueError("El consecutivo inicial no puede ser mayor a 999.")


def formatear_identificador(serial: str, consecutivo: int) -> str:
    if consecutivo > CONSECUTIVO_MAXIMO:
        raise ValueError("El consecutivo máximo soportado es 999.")

    return f"{serial}-{consecutivo:03d}"


def crear_registros(seriales: list[str], inicio: int) -> list[tuple[str, int]]:
    validar_inicio(inicio)

    ultimo = inicio + len(seriales) - 1

    if ultimo > CONSECUTIVO_MAXIMO:
        raise ValueError(
            f"El lote llegaría hasta {ultimo:03d}, "
            "pero el consecutivo máximo soportado es 999."
        )

    return [(serial, inicio + indice) for indice, serial in enumerate(seriales)]


def detectar_dialecto_csv(texto: str) -> csv.Dialect:
    muestra = texto[:2048]

    try:
        return csv.Sniffer().sniff(muestra, delimiters=",;\t|")
    except csv.Error:
        class Dialecto(csv.excel):
            delimiter = ","

        candidatos = [",", ";", "\t", "|"]
        Dialecto.delimiter = max(candidatos, key=texto.count)
        return Dialecto


def filas_csv(texto: str) -> list[list[str]]:
    if not texto.strip():
        return []

    dialecto = detectar_dialecto_csv(texto)
    reader = csv.reader(io.StringIO(texto), dialecto)
    filas = []

    for fila in reader:
        limpia = [normalizar_espacios(celda) for celda in fila]

        if any(limpia):
            filas.append(limpia)

    return filas


def es_encabezado(fila: list[str], claves: set[str]) -> bool:
    normalizadas = {normalizar_clave(celda) for celda in fila}
    return bool(normalizadas & claves)


def indice_encabezado(encabezado: list[str], aliases: set[str]) -> int | None:
    normalizado = [normalizar_clave(celda) for celda in encabezado]

    for alias in aliases:
        if alias in normalizado:
            return normalizado.index(alias)

    return None


def valor_por_indice(fila: list[str], indice: int | None) -> str:
    if indice is None or indice >= len(fila):
        return ""

    return fila[indice].strip()


def validar_campo(valor: str, nombre: str, num_linea: int) -> str:
    valor = normalizar_espacios(valor)

    if not valor:
        raise ValueError(f"Línea {num_linea}: falta {nombre}.")

    return valor


def normalizar_seccion(seccion: str, num_linea: int) -> str:
    clave = normalizar_clave(seccion)

    if clave not in SECCIONES_DOCENTES:
        opciones = ", ".join(SECCIONES_DOCENTES.values())
        raise ValueError(
            f"Línea {num_linea}: sección inválida {seccion!r}. "
            f"Usa una de estas: {opciones}."
        )

    return SECCIONES_DOCENTES[clave]


def normalizar_alumnos(texto: str) -> list[EtiquetaAlumno]:
    filas = filas_csv(texto)

    if not filas:
        raise ValueError("No hay alumnos para generar.")

    aliases = {
        "matricula": {"matricula", "numero de matricula", "num matricula"},
        "nombre": {"nombre", "nombre completo", "alumno"},
        "grado_grupo": {"grado grupo", "grado y grupo", "grado/grupo", "grupo"},
        "grado": {"grado"},
        "serie": {"serie", "serial", "numero de serie", "num serie", "equipo"},
    }
    claves = set().union(*aliases.values())
    encabezado = filas[0] if es_encabezado(filas[0], claves) else None
    alumnos = []

    if encabezado:
        idx_matricula = indice_encabezado(encabezado, aliases["matricula"])
        idx_nombre = indice_encabezado(encabezado, aliases["nombre"])
        idx_grado_grupo = indice_encabezado(encabezado, aliases["grado_grupo"])
        idx_grado = indice_encabezado(encabezado, aliases["grado"])
        idx_serie = indice_encabezado(encabezado, aliases["serie"])
        filas_datos = filas[1:]
        base_linea = 2
    else:
        idx_matricula = idx_nombre = idx_grado_grupo = idx_grado = idx_serie = None
        filas_datos = filas
        base_linea = 1

    for offset, fila in enumerate(filas_datos):
        num_linea = base_linea + offset

        if encabezado:
            matricula = valor_por_indice(fila, idx_matricula)
            nombre = valor_por_indice(fila, idx_nombre)
            grado_grupo = valor_por_indice(fila, idx_grado_grupo)
            grado = valor_por_indice(fila, idx_grado)
            serie = valor_por_indice(fila, idx_serie)

            if grado and grado_grupo and grado != grado_grupo:
                grado_grupo = f"{grado} {grado_grupo}"
            elif grado and not grado_grupo:
                grado_grupo = grado
        elif len(fila) >= 5:
            matricula, nombre, grado, grupo, serie = fila[:5]
            grado_grupo = f"{grado} {grupo}".strip()
        elif len(fila) >= 4:
            matricula, nombre, grado_grupo, serie = fila[:4]
        else:
            raise ValueError(
                f"Línea {num_linea}: usa matrícula, nombre, grado/grupo y serie."
            )

        alumnos.append(
            EtiquetaAlumno(
                matricula=validar_campo(matricula, "matrícula", num_linea),
                nombre=validar_campo(nombre, "nombre", num_linea),
                grado_grupo=validar_campo(grado_grupo, "grado/grupo", num_linea),
                serie=validar_campo(serie, "número de serie", num_linea),
            )
        )

    if not alumnos:
        raise ValueError("No hay alumnos para generar.")

    return alumnos


def normalizar_docentes(texto: str) -> list[EtiquetaDocente]:
    filas = filas_csv(texto)

    if not filas:
        raise ValueError("No hay docentes para generar.")

    aliases = {
        "nombre": {"nombre", "nombre completo", "docente"},
        "seccion": {"seccion", "nivel"},
        "serie": {"serie", "serial", "numero de serie", "num serie", "equipo"},
    }
    claves = set().union(*aliases.values())
    encabezado = filas[0] if es_encabezado(filas[0], claves) else None
    docentes = []

    if encabezado:
        idx_nombre = indice_encabezado(encabezado, aliases["nombre"])
        idx_seccion = indice_encabezado(encabezado, aliases["seccion"])
        idx_serie = indice_encabezado(encabezado, aliases["serie"])
        filas_datos = filas[1:]
        base_linea = 2
    else:
        idx_nombre = idx_seccion = idx_serie = None
        filas_datos = filas
        base_linea = 1

    for offset, fila in enumerate(filas_datos):
        num_linea = base_linea + offset

        if encabezado:
            nombre = valor_por_indice(fila, idx_nombre)
            seccion = valor_por_indice(fila, idx_seccion)
            serie = valor_por_indice(fila, idx_serie)
        elif len(fila) >= 3:
            nombre, seccion, serie = fila[:3]
        else:
            raise ValueError(f"Línea {num_linea}: usa nombre, sección y serie.")

        docentes.append(
            EtiquetaDocente(
                nombre=validar_campo(nombre, "nombre", num_linea),
                seccion=normalizar_seccion(
                    validar_campo(seccion, "sección", num_linea),
                    num_linea,
                ),
                serie=validar_campo(serie, "número de serie", num_linea),
            )
        )

    if not docentes:
        raise ValueError("No hay docentes para generar.")

    return docentes


def posicion_etiqueta(fila: int, columna: int) -> tuple[float, float]:
    x = GRID_LEFT + columna * (LABEL_W + GAP_X)
    y = PAGE_H - TOP_MARGIN - LABEL_H - fila * (LABEL_H + GAP_Y)
    return x, y


def dibujar_guias(c: canvas.Canvas):
    c.saveState()
    c.setLineWidth(0.25)
    c.setDash(1, 1)

    for fila in range(ROWS):
        for columna in range(COLS):
            x, y = posicion_etiqueta(fila, columna)
            c.rect(x, y, LABEL_W, LABEL_H, stroke=1, fill=0)

    c.restoreState()


def tamano_identificador(texto: str) -> float:
    return SERIAL_SIZE_SHORT if len(texto) <= 15 else SERIAL_SIZE_LONG


def ancho_texto(texto: str, fuente: str, tamano: float) -> float:
    return pdfmetrics.stringWidth(texto, fuente, tamano)


def tamano_para_ancho(
    texto: str,
    fuente: str,
    ancho_max: float,
    tamano_max: float,
    tamano_min: float = 5.5,
) -> float:
    tamano = tamano_max

    while tamano > tamano_min and ancho_texto(texto, fuente, tamano) > ancho_max:
        tamano -= 0.25

    return max(tamano, tamano_min)


def truncar_texto(texto: str, fuente: str, tamano: float, ancho_max: float) -> str:
    if ancho_texto(texto, fuente, tamano) <= ancho_max:
        return texto

    elipsis = "..."
    disponible = ancho_max - ancho_texto(elipsis, fuente, tamano)

    if disponible <= 0:
        return elipsis

    recortado = texto

    while recortado and ancho_texto(recortado, fuente, tamano) > disponible:
        recortado = recortado[:-1]

    return recortado.rstrip() + elipsis


def partir_texto(
    texto: str,
    fuente: str,
    tamano: float,
    ancho_max: float,
    max_lineas: int,
) -> list[str]:
    palabras = texto.split()
    lineas = []
    actual = ""

    for palabra in palabras:
        candidato = f"{actual} {palabra}".strip()

        if not actual or ancho_texto(candidato, fuente, tamano) <= ancho_max:
            actual = candidato
            continue

        lineas.append(actual)
        actual = palabra

        if len(lineas) == max_lineas:
            break

    if actual and len(lineas) < max_lineas:
        lineas.append(actual)

    if len(lineas) == max_lineas:
        consumido = " ".join(lineas)

        if len(consumido) < len(texto):
            lineas[-1] = truncar_texto(lineas[-1], fuente, tamano, ancho_max)

    return lineas


def dibujar_texto_ajustado(
    c: canvas.Canvas,
    texto: str,
    x: float,
    y: float,
    ancho_max: float,
    fuente: str,
    tamano_max: float,
    tamano_min: float = 5.5,
):
    tamano = tamano_para_ancho(texto, fuente, ancho_max, tamano_max, tamano_min)
    texto = truncar_texto(texto, fuente, tamano, ancho_max)
    c.setFont(fuente, tamano)
    c.drawString(x, y, texto)


def dibujar_etiqueta(c: canvas.Canvas, x: float, y: float, identificador: str):
    barcode = Code128(
        identificador,
        barWidth=BAR_WIDTH,
        barHeight=BAR_HEIGHT,
        humanReadable=False,
        quiet=True,
        lquiet=BAR_QUIET,
        rquiet=BAR_QUIET,
    )

    max_barcode_w = LABEL_W - 4 * mm

    if barcode.width > max_barcode_w:
        raise ValueError(
            f"El código {identificador!r} ocupa "
            f"{barcode.width / mm:.1f} mm y excede "
            f"el ancho disponible de {max_barcode_w / mm:.1f} mm."
        )

    barcode_x = x + (LABEL_W - barcode.width) / 2
    barcode_y = y + 11 * mm
    barcode.drawOn(c, barcode_x, barcode_y)

    c.setFont("Helvetica-Bold", tamano_identificador(identificador))
    c.drawCentredString(x + LABEL_W / 2, y + 5.5 * mm, identificador)


def dibujar_etiqueta_alumno(c: canvas.Canvas, x: float, y: float, alumno: EtiquetaAlumno):
    left = x + 3 * mm
    ancho = LABEL_W - 6 * mm
    nombre_lineas = partir_texto(alumno.nombre, "Helvetica-Bold", 7.6, ancho, 2)

    dibujar_texto_ajustado(
        c,
        f"MATRICULA: {alumno.matricula}",
        left,
        y + 25.2 * mm,
        ancho,
        "Helvetica-Bold",
        7.3,
    )

    for idx in range(2):
        texto = nombre_lineas[idx] if idx < len(nombre_lineas) else ""
        dibujar_texto_ajustado(
            c,
            texto,
            left,
            y + (20.0 - idx * 4.1) * mm,
            ancho,
            "Helvetica-Bold",
            7.6,
        )

    dibujar_texto_ajustado(
        c,
        f"GRADO/GRUPO: {alumno.grado_grupo}",
        left,
        y + 10.1 * mm,
        ancho,
        "Helvetica",
        7.0,
    )
    dibujar_texto_ajustado(
        c,
        f"SERIE: {alumno.serie}",
        left,
        y + 5.5 * mm,
        ancho,
        "Helvetica",
        7.0,
    )


def dibujar_etiqueta_docente(c: canvas.Canvas, x: float, y: float, docente: EtiquetaDocente):
    left = x + 3 * mm
    ancho = LABEL_W - 6 * mm
    nombre_lineas = partir_texto(docente.nombre, "Helvetica-Bold", 8.2, ancho, 2)

    for idx in range(2):
        texto = nombre_lineas[idx] if idx < len(nombre_lineas) else ""
        dibujar_texto_ajustado(
            c,
            texto,
            left,
            y + (23.8 - idx * 4.4) * mm,
            ancho,
            "Helvetica-Bold",
            8.2,
        )

    dibujar_texto_ajustado(
        c,
        f"SECCION: {docente.seccion}",
        left,
        y + 12.3 * mm,
        ancho,
        "Helvetica",
        7.3,
    )
    dibujar_texto_ajustado(
        c,
        f"SERIE: {docente.serie}",
        left,
        y + 6.5 * mm,
        ancho,
        "Helvetica",
        7.3,
    )


def dibujar_pagina(c: canvas.Canvas, grupo: list[tuple[str, int]], guias: bool):
    if guias:
        dibujar_guias(c)

    for posicion, (serial, consecutivo) in enumerate(grupo):
        fila = posicion // COLS
        columna = posicion % COLS
        x, y = posicion_etiqueta(fila, columna)
        identificador = formatear_identificador(serial, consecutivo)
        dibujar_etiqueta(c, x, y, identificador)


def dibujar_pagina_alumnos(c: canvas.Canvas, grupo: list[EtiquetaAlumno], guias: bool):
    if guias:
        dibujar_guias(c)

    for posicion, alumno in enumerate(grupo):
        fila = posicion // COLS
        columna = posicion % COLS
        x, y = posicion_etiqueta(fila, columna)
        dibujar_etiqueta_alumno(c, x, y, alumno)


def dibujar_pagina_docentes(c: canvas.Canvas, grupo: list[EtiquetaDocente], guias: bool):
    if guias:
        dibujar_guias(c)

    for posicion, docente in enumerate(grupo):
        fila = posicion // COLS
        columna = posicion % COLS
        x, y = posicion_etiqueta(fila, columna)
        dibujar_etiqueta_docente(c, x, y, docente)


def generar_pdf(seriales: list[str], salida: Path, inicio: int = 1, guias: bool = False):
    salida.parent.mkdir(parents=True, exist_ok=True)

    c = canvas.Canvas(str(salida), pagesize=(PAGE_W, PAGE_H))
    c.setTitle("Etiquetas de inventario Code 128")

    registros = crear_registros(seriales, inicio)

    for inicio_pagina in range(0, len(registros), ETIQUETAS_POR_HOJA):
        grupo = registros[inicio_pagina:inicio_pagina + ETIQUETAS_POR_HOJA]
        dibujar_pagina(c, grupo, guias)
        c.showPage()

    c.save()


def generar_pdf_alumnos(
    alumnos: list[EtiquetaAlumno],
    salida: Path,
    guias: bool = False,
):
    salida.parent.mkdir(parents=True, exist_ok=True)

    c = canvas.Canvas(str(salida), pagesize=(PAGE_W, PAGE_H))
    c.setTitle("Etiquetas de alumnos")

    for inicio_pagina in range(0, len(alumnos), ETIQUETAS_POR_HOJA):
        grupo = alumnos[inicio_pagina:inicio_pagina + ETIQUETAS_POR_HOJA]
        dibujar_pagina_alumnos(c, grupo, guias)
        c.showPage()

    c.save()


def generar_pdf_docentes(
    docentes: list[EtiquetaDocente],
    salida: Path,
    guias: bool = False,
):
    salida.parent.mkdir(parents=True, exist_ok=True)

    c = canvas.Canvas(str(salida), pagesize=(PAGE_W, PAGE_H))
    c.setTitle("Etiquetas de docentes")

    for inicio_pagina in range(0, len(docentes), ETIQUETAS_POR_HOJA):
        grupo = docentes[inicio_pagina:inicio_pagina + ETIQUETAS_POR_HOJA]
        dibujar_pagina_docentes(c, grupo, guias)
        c.showPage()

    c.save()


def abrir_archivo(ruta: Path):
    if not ruta.exists():
        raise FileNotFoundError(f"No existe el archivo: {ruta}")

    if sys.platform.startswith("win"):
        os.startfile(str(ruta))
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(ruta)])
    else:
        subprocess.Popen(["xdg-open", str(ruta)])


def paginas_para(cantidad: int) -> int:
    return (cantidad + ETIQUETAS_POR_HOJA - 1) // ETIQUETAS_POR_HOJA


class AplicacionEtiquetas(tk.Tk):
    def __init__(self):
        super().__init__()

        self.title("Generador de etiquetas de inventario")
        self.geometry("980x720")
        self.minsize(860, 640)

        self.ruta_codigos = tk.StringVar(value=str(Path.cwd() / "etiquetas.pdf"))
        self.ruta_alumnos = tk.StringVar(value=str(Path.cwd() / "etiquetas-alumnos.pdf"))
        self.ruta_docentes = tk.StringVar(value=str(Path.cwd() / "etiquetas-docentes.pdf"))
        self.inicio_var = tk.StringVar(value="1")
        self.guias_codigos_var = tk.BooleanVar(value=False)
        self.guias_alumnos_var = tk.BooleanVar(value=False)
        self.guias_docentes_var = tk.BooleanVar(value=False)
        self.estado_var = tk.StringVar(value="Selecciona una función para generar etiquetas.")
        self.resumen_codigos_var = tk.StringVar(value="0 etiquetas · 0 páginas")
        self.resumen_alumnos_var = tk.StringVar(value="0 etiquetas · 0 páginas")
        self.resumen_docentes_var = tk.StringVar(value="0 etiquetas · 0 páginas")

        self._crear_interfaz()
        self._actualizar_resumen_codigos()
        self._actualizar_resumen_alumnos()
        self._actualizar_resumen_docentes()

    def _crear_interfaz(self):
        contenedor = ttk.Frame(self, padding=16)
        contenedor.pack(fill="both", expand=True)

        ttk.Label(
            contenedor,
            text="Generador de etiquetas",
            font=("Segoe UI", 18, "bold"),
        ).pack(anchor="w")

        ttk.Label(
            contenedor,
            text="Códigos Code 128, etiquetas de alumnos y etiquetas de docentes.",
        ).pack(anchor="w", pady=(2, 14))

        self.notebook = ttk.Notebook(contenedor)
        self.notebook.pack(fill="both", expand=True)

        self.tab_codigos = ttk.Frame(self.notebook, padding=12)
        self.tab_alumnos = ttk.Frame(self.notebook, padding=12)
        self.tab_docentes = ttk.Frame(self.notebook, padding=12)

        self.notebook.add(self.tab_codigos, text="Códigos")
        self.notebook.add(self.tab_alumnos, text="Alumnos")
        self.notebook.add(self.tab_docentes, text="Docentes")

        self._crear_tab_codigos(self.tab_codigos)
        self._crear_tab_alumnos(self.tab_alumnos)
        self._crear_tab_docentes(self.tab_docentes)

        ttk.Separator(contenedor).pack(fill="x", pady=(14, 8))
        ttk.Label(contenedor, textvariable=self.estado_var).pack(anchor="w")
        ttk.Label(
            contenedor,
            text="Impresión: usar Tamaño real / 100 %. No usar Ajustar o Fit.",
        ).pack(anchor="w", pady=(3, 0))

    def _crear_tab_codigos(self, parent: ttk.Frame):
        ttk.Label(
            parent,
            text="Formato: NUMERO_DE_SERIE-001 · 12 etiquetas por hoja · Code 128",
        ).pack(anchor="w", pady=(0, 10))

        marco_seriales = ttk.LabelFrame(parent, text="Números de serie", padding=10)
        marco_seriales.pack(fill="both", expand=True)

        barra_seriales = ttk.Frame(marco_seriales)
        barra_seriales.pack(fill="x", pady=(0, 8))

        ttk.Button(barra_seriales, text="Cargar TXT", command=self._cargar_txt_codigos).pack(side="left")
        ttk.Button(barra_seriales, text="Limpiar", command=self._limpiar_codigos).pack(side="left", padx=(8, 0))
        ttk.Label(barra_seriales, textvariable=self.resumen_codigos_var).pack(side="right")

        self.texto_seriales = self._crear_area_texto(marco_seriales, self._texto_codigos_modificado)

        marco_config = ttk.LabelFrame(parent, text="Configuración", padding=10)
        marco_config.pack(fill="x", pady=(12, 0))

        fila1 = ttk.Frame(marco_config)
        fila1.pack(fill="x")

        ttk.Label(fila1, text="Consecutivo inicial:").pack(side="left")

        self.spin_inicio = ttk.Spinbox(
            fila1,
            from_=1,
            to=999,
            width=8,
            textvariable=self.inicio_var,
            command=self._actualizar_resumen_codigos,
        )
        self.spin_inicio.pack(side="left", padx=(8, 20))
        self.spin_inicio.bind("<KeyRelease>", lambda _e: self._actualizar_resumen_codigos())

        ttk.Checkbutton(
            fila1,
            text="Imprimir guías de calibración",
            variable=self.guias_codigos_var,
        ).pack(side="left")

        self._crear_selector_salida(
            marco_config,
            self.ruta_codigos,
            "etiquetas.pdf",
        )

        acciones = ttk.Frame(parent)
        acciones.pack(fill="x", pady=(14, 0))

        self.boton_generar_codigos = ttk.Button(
            acciones,
            text="Generar PDF",
            command=self._generar_codigos,
        )
        self.boton_generar_codigos.pack(side="right")

        self.boton_abrir_codigos = ttk.Button(
            acciones,
            text="Abrir último PDF",
            command=lambda: self._abrir_pdf(self.ruta_codigos),
            state="disabled",
        )
        self.boton_abrir_codigos.pack(side="right", padx=(0, 8))

    def _crear_tab_alumnos(self, parent: ttk.Frame):
        ttk.Label(
            parent,
            text=(
                "Formato con encabezados: matricula,nombre,grado_grupo,serie. "
                "También acepta: matricula,nombre,grado,grupo,serie."
            ),
        ).pack(anchor="w", pady=(0, 10))

        marco = ttk.LabelFrame(parent, text="Datos de alumnos", padding=10)
        marco.pack(fill="both", expand=True)

        barra = ttk.Frame(marco)
        barra.pack(fill="x", pady=(0, 8))

        ttk.Button(barra, text="Cargar CSV/TXT", command=self._cargar_txt_alumnos).pack(side="left")
        ttk.Button(barra, text="Pegar ejemplo", command=self._ejemplo_alumnos).pack(side="left", padx=(8, 0))
        ttk.Button(barra, text="Limpiar", command=self._limpiar_alumnos).pack(side="left", padx=(8, 0))
        ttk.Label(barra, textvariable=self.resumen_alumnos_var).pack(side="right")

        self.texto_alumnos = self._crear_area_texto(marco, self._texto_alumnos_modificado)

        marco_config = ttk.LabelFrame(parent, text="Configuración", padding=10)
        marco_config.pack(fill="x", pady=(12, 0))

        ttk.Checkbutton(
            marco_config,
            text="Imprimir guías de calibración",
            variable=self.guias_alumnos_var,
        ).pack(anchor="w")

        self._crear_selector_salida(
            marco_config,
            self.ruta_alumnos,
            "etiquetas-alumnos.pdf",
        )

        acciones = ttk.Frame(parent)
        acciones.pack(fill="x", pady=(14, 0))

        ttk.Button(acciones, text="Generar PDF", command=self._generar_alumnos).pack(side="right")
        self.boton_abrir_alumnos = ttk.Button(
            acciones,
            text="Abrir último PDF",
            command=lambda: self._abrir_pdf(self.ruta_alumnos),
            state="disabled",
        )
        self.boton_abrir_alumnos.pack(side="right", padx=(0, 8))

    def _crear_tab_docentes(self, parent: ttk.Frame):
        ttk.Label(
            parent,
            text="Formato con encabezados: nombre,seccion,serie. Secciones: Estancia, Preescolar, Primaria o Secundaria.",
        ).pack(anchor="w", pady=(0, 10))

        marco = ttk.LabelFrame(parent, text="Datos de docentes", padding=10)
        marco.pack(fill="both", expand=True)

        barra = ttk.Frame(marco)
        barra.pack(fill="x", pady=(0, 8))

        ttk.Button(barra, text="Cargar CSV/TXT", command=self._cargar_txt_docentes).pack(side="left")
        ttk.Button(barra, text="Pegar ejemplo", command=self._ejemplo_docentes).pack(side="left", padx=(8, 0))
        ttk.Button(barra, text="Limpiar", command=self._limpiar_docentes).pack(side="left", padx=(8, 0))
        ttk.Label(barra, textvariable=self.resumen_docentes_var).pack(side="right")

        self.texto_docentes = self._crear_area_texto(marco, self._texto_docentes_modificado)

        marco_config = ttk.LabelFrame(parent, text="Configuración", padding=10)
        marco_config.pack(fill="x", pady=(12, 0))

        ttk.Checkbutton(
            marco_config,
            text="Imprimir guías de calibración",
            variable=self.guias_docentes_var,
        ).pack(anchor="w")

        self._crear_selector_salida(
            marco_config,
            self.ruta_docentes,
            "etiquetas-docentes.pdf",
        )

        acciones = ttk.Frame(parent)
        acciones.pack(fill="x", pady=(14, 0))

        ttk.Button(acciones, text="Generar PDF", command=self._generar_docentes).pack(side="right")
        self.boton_abrir_docentes = ttk.Button(
            acciones,
            text="Abrir último PDF",
            command=lambda: self._abrir_pdf(self.ruta_docentes),
            state="disabled",
        )
        self.boton_abrir_docentes.pack(side="right", padx=(0, 8))

    def _crear_area_texto(self, parent: ttk.Frame, callback) -> tk.Text:
        marco_texto = ttk.Frame(parent)
        marco_texto.pack(fill="both", expand=True)

        texto = tk.Text(
            marco_texto,
            wrap="none",
            undo=True,
            font=("Consolas", 11),
            height=14,
        )
        texto.pack(side="left", fill="both", expand=True)

        scroll_y = ttk.Scrollbar(marco_texto, orient="vertical", command=texto.yview)
        scroll_y.pack(side="right", fill="y")
        texto.configure(yscrollcommand=scroll_y.set)
        texto.bind("<<Modified>>", callback)

        return texto

    def _crear_selector_salida(self, parent: ttk.Frame, variable: tk.StringVar, default_name: str):
        fila = ttk.Frame(parent)
        fila.pack(fill="x", pady=(10, 0))

        ttk.Label(fila, text="Guardar PDF en:").pack(side="left")

        ttk.Entry(fila, textvariable=variable).pack(
            side="left",
            fill="x",
            expand=True,
            padx=(8, 8),
        )

        ttk.Button(
            fila,
            text="Examinar...",
            command=lambda: self._seleccionar_salida(variable, default_name),
        ).pack(side="right")

    def _texto_codigos_modificado(self, _event=None):
        if self.texto_seriales.edit_modified():
            self.texto_seriales.edit_modified(False)
            self._actualizar_resumen_codigos()

    def _texto_alumnos_modificado(self, _event=None):
        if self.texto_alumnos.edit_modified():
            self.texto_alumnos.edit_modified(False)
            self._actualizar_resumen_alumnos()

    def _texto_docentes_modificado(self, _event=None):
        if self.texto_docentes.edit_modified():
            self.texto_docentes.edit_modified(False)
            self._actualizar_resumen_docentes()

    def _obtener_seriales_sin_error(self) -> list[str]:
        texto = self.texto_seriales.get("1.0", "end-1c")

        if not texto.strip():
            return []

        try:
            return normalizar_seriales(texto)
        except ValueError:
            return [linea.strip() for linea in texto.splitlines() if linea.strip()]

    def _actualizar_resumen_codigos(self):
        seriales = self._obtener_seriales_sin_error()
        cantidad = len(seriales)
        paginas = paginas_para(cantidad)

        try:
            inicio = int(self.inicio_var.get())
            ultimo = inicio + cantidad - 1
            rango = f" · {inicio:03d}-{ultimo:03d}" if cantidad else ""
        except ValueError:
            rango = ""

        self.resumen_codigos_var.set(f"{cantidad} etiquetas · {paginas} páginas{rango}")

    def _actualizar_resumen_alumnos(self):
        texto = self.texto_alumnos.get("1.0", "end-1c")
        cantidad = self._contar_registros(texto, normalizar_alumnos)
        paginas = paginas_para(cantidad)
        self.resumen_alumnos_var.set(f"{cantidad} etiquetas · {paginas} páginas")

    def _actualizar_resumen_docentes(self):
        texto = self.texto_docentes.get("1.0", "end-1c")
        cantidad = self._contar_registros(texto, normalizar_docentes)
        paginas = paginas_para(cantidad)
        self.resumen_docentes_var.set(f"{cantidad} etiquetas · {paginas} páginas")

    def _contar_registros(self, texto: str, parser) -> int:
        if not texto.strip():
            return 0

        try:
            return len(parser(texto))
        except ValueError:
            return max(0, len(filas_csv(texto)) - 1)

    def _cargar_texto_en(self, destino: tk.Text, resumen_callback):
        ruta = filedialog.askopenfilename(
            title="Seleccionar archivo",
            filetypes=[
                ("CSV o texto", "*.csv *.txt"),
                ("CSV", "*.csv"),
                ("Texto", "*.txt"),
                ("Todos los archivos", "*.*"),
            ],
        )

        if not ruta:
            return

        try:
            texto = Path(ruta).read_text(encoding="utf-8-sig")
        except Exception as exc:
            messagebox.showerror("Error", f"No se pudo leer el archivo.\n\n{exc}")
            return

        destino.delete("1.0", "end")
        destino.insert("1.0", texto)
        resumen_callback()
        self.estado_var.set(f"Archivo cargado: {Path(ruta).name}")

    def _cargar_txt_codigos(self):
        self._cargar_texto_en(self.texto_seriales, self._actualizar_resumen_codigos)

    def _cargar_txt_alumnos(self):
        self._cargar_texto_en(self.texto_alumnos, self._actualizar_resumen_alumnos)

    def _cargar_txt_docentes(self):
        self._cargar_texto_en(self.texto_docentes, self._actualizar_resumen_docentes)

    def _limpiar_codigos(self):
        self.texto_seriales.delete("1.0", "end")
        self._actualizar_resumen_codigos()
        self.estado_var.set("Pega los números de serie, uno por línea.")

    def _limpiar_alumnos(self):
        self.texto_alumnos.delete("1.0", "end")
        self._actualizar_resumen_alumnos()
        self.estado_var.set("Pega o carga los datos de alumnos.")

    def _limpiar_docentes(self):
        self.texto_docentes.delete("1.0", "end")
        self._actualizar_resumen_docentes()
        self.estado_var.set("Pega o carga los datos de docentes.")

    def _ejemplo_alumnos(self):
        ejemplo = (
            "matricula,nombre,grado_grupo,serie\n"
            "A00123,Ana Sofia Martinez Lopez,3A,T6NXLP00W65823E\n"
            "A00124,Carlos Emiliano Gomez Ruiz,5B,PF306BAC001\n"
        )
        self.texto_alumnos.delete("1.0", "end")
        self.texto_alumnos.insert("1.0", ejemplo)
        self._actualizar_resumen_alumnos()

    def _ejemplo_docentes(self):
        ejemplo = (
            "nombre,seccion,serie\n"
            "Mariana Torres Hernandez,Primaria,T6NXLP00W65823E\n"
            "Luis Fernando Perez Cano,Secundaria,PF306BAC001\n"
        )
        self.texto_docentes.delete("1.0", "end")
        self.texto_docentes.insert("1.0", ejemplo)
        self._actualizar_resumen_docentes()

    def _seleccionar_salida(self, variable: tk.StringVar, default_name: str):
        ruta_actual = Path(variable.get())

        ruta = filedialog.asksaveasfilename(
            title="Guardar etiquetas",
            defaultextension=".pdf",
            initialfile=ruta_actual.name or default_name,
            filetypes=[("Documento PDF", "*.pdf")],
        )

        if ruta:
            variable.set(ruta)

    def _ruta_pdf(self, variable: tk.StringVar) -> Path:
        salida_texto = variable.get().strip()

        if not salida_texto:
            raise ValueError("Selecciona una ruta para guardar el PDF.")

        salida = Path(salida_texto)

        if salida.suffix.lower() != ".pdf":
            salida = salida.with_suffix(".pdf")
            variable.set(str(salida))

        return salida

    def _generar_codigos(self):
        try:
            texto = self.texto_seriales.get("1.0", "end-1c")
            seriales = normalizar_seriales(texto)

            try:
                inicio = int(self.inicio_var.get())
            except ValueError:
                raise ValueError("El consecutivo inicial debe ser un número entero.")

            salida = self._ruta_pdf(self.ruta_codigos)
            generar_pdf(
                seriales,
                salida,
                inicio=inicio,
                guias=self.guias_codigos_var.get(),
            )

            ultimo = inicio + len(seriales) - 1
            paginas = paginas_para(len(seriales))
            self.estado_var.set(f"PDF generado correctamente: {salida}")
            self.boton_abrir_codigos.configure(state="normal")

            messagebox.showinfo(
                "PDF generado",
                (
                    f"Se generó el PDF correctamente.\n\n"
                    f"Etiquetas: {len(seriales)}\n"
                    f"Páginas: {paginas}\n"
                    f"Consecutivos: {inicio:03d} - {ultimo:03d}\n\n"
                    f"Archivo:\n{salida}"
                ),
            )

        except Exception as exc:
            messagebox.showerror("No se pudo generar el PDF", str(exc))

    def _generar_alumnos(self):
        try:
            alumnos = normalizar_alumnos(self.texto_alumnos.get("1.0", "end-1c"))
            salida = self._ruta_pdf(self.ruta_alumnos)
            generar_pdf_alumnos(alumnos, salida, guias=self.guias_alumnos_var.get())
            paginas = paginas_para(len(alumnos))
            self.estado_var.set(f"PDF de alumnos generado correctamente: {salida}")
            self.boton_abrir_alumnos.configure(state="normal")

            messagebox.showinfo(
                "PDF generado",
                (
                    f"Se generó el PDF de alumnos correctamente.\n\n"
                    f"Etiquetas: {len(alumnos)}\n"
                    f"Páginas: {paginas}\n\n"
                    f"Archivo:\n{salida}"
                ),
            )

        except Exception as exc:
            messagebox.showerror("No se pudo generar el PDF", str(exc))

    def _generar_docentes(self):
        try:
            docentes = normalizar_docentes(self.texto_docentes.get("1.0", "end-1c"))
            salida = self._ruta_pdf(self.ruta_docentes)
            generar_pdf_docentes(docentes, salida, guias=self.guias_docentes_var.get())
            paginas = paginas_para(len(docentes))
            self.estado_var.set(f"PDF de docentes generado correctamente: {salida}")
            self.boton_abrir_docentes.configure(state="normal")

            messagebox.showinfo(
                "PDF generado",
                (
                    f"Se generó el PDF de docentes correctamente.\n\n"
                    f"Etiquetas: {len(docentes)}\n"
                    f"Páginas: {paginas}\n\n"
                    f"Archivo:\n{salida}"
                ),
            )

        except Exception as exc:
            messagebox.showerror("No se pudo generar el PDF", str(exc))

    def _abrir_pdf(self, variable: tk.StringVar):
        try:
            ruta = self._ruta_pdf(variable)
            abrir_archivo(ruta)
        except Exception as exc:
            messagebox.showerror("Error", f"No se pudo abrir el PDF.\n\n{exc}")


def main():
    app = AplicacionEtiquetas()
    app.mainloop()


if __name__ == "__main__":
    main()