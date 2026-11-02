"""Contenido estructurado que el agente redacta; el servidor aplica portada, APA 7 y exportación."""

import re
import unicodedata
from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


# Caracteres que rompen XML 1.0, sustitutos sueltos y controles bidi que permiten suplantar texto.
INVALID_TEXT = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f\ud800-\udfff\ufffe\uffff\u202a-\u202e\u2066-\u2069]")
INVISIBLE_IN_URL = re.compile("[\\s\u200b-\u200f\u2028-\u202e\u2060-\u2069\ufeff]")
INLINE = re.compile(
    r"(?P<escape>\\[*\[\]\\])"
    r"|\*\*\*(?P<bolditalic>.+?)\*\*\*"
    r"|\*\*(?P<bold>.+?)\*\*"
    r"|\*(?P<italic>[^*\s](?:[^*]*?[^*\s])?)\*"
    r"|\[(?P<label>[^\]]+)\]\((?P<target>(?:[^()\s]|\([^()\s]*\))+)\)"
    r"|(?P<url>https?://[^\s<>\"]+)"
)
# Campos de la portada en la plantilla: {{titulo}}, {{materia}}, {{nombre_docente}}, {{estudiantes}}...
COVER_FIELDS = ("materia", "nombre_docente", "estudiantes", "carrera", "curso", "anio")
TEMPLATE_FIELDS = ("titulo", *COVER_FIELDS)
REQUIRED_COVER_FIELDS = COVER_FIELDS
MAX_STUDENTS = 6
MAX_TOTAL_CHARACTERS = 400_000
TEMPLATE_TOKEN = re.compile(r"\{\{\s*(?:" + "|".join(TEMPLATE_FIELDS) + r")\s*\}\}")


def no_template_tokens(value: str) -> str:
    if TEMPLATE_TOKEN.search(value):
        raise ValueError("El texto no puede contener campos de plantilla como {{nombre_docente}}; escribe el dato real.")
    return value


def clean_text(value: str) -> str:
    # Las tabulaciones se convierten en cuatro espacios: conserva la sangría del código.
    return INVALID_TEXT.sub("", value.replace("\t", "    ").replace("\r\n", "\n").replace("\r", "\n"))


def check_url(url: str) -> str:
    if INVISIBLE_IN_URL.search(url):
        raise ValueError(f"El enlace contiene espacios o caracteres invisibles: {url!r}")
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname or parts.username or parts.password:
        raise ValueError(f"Solo se admiten enlaces http(s) completos sin usuario: {url!r}")
    return url


def parse_inline(text: str) -> list[dict]:
    """Divide **negrita**, *cursiva*, [texto](url) y URLs sueltas en segmentos con formato."""
    segments: list[dict] = []

    def add(value: str, *, bold=False, italic=False, link=None):
        if not value:
            return
        last = segments[-1] if segments else None
        if last and (last["bold"], last["italic"], last["link"]) == (bold, italic, link):
            last["text"] += value
        else:
            segments.append({"text": value, "bold": bold, "italic": italic, "link": link})

    position = 0
    for match in INLINE.finditer(text):
        add(text[position:match.start()])
        position = match.end()
        if match.group("escape"):
            add(match.group("escape")[1])
        elif match.group("bolditalic") is not None or match.group("bold") is not None or match.group("italic") is not None:
            # El contenido enfatizado se vuelve a analizar: enlaces y reglas de GitHub siguen aplicando.
            inner = match.group("bolditalic") or match.group("bold") or match.group("italic")
            bold = match.group("bolditalic") is not None or match.group("bold") is not None
            italic = match.group("bolditalic") is not None or match.group("italic") is not None
            for segment in parse_inline(inner):
                add(segment["text"], bold=bold or segment["bold"], italic=italic or segment["italic"], link=segment["link"])
        elif match.group("target") is not None:
            label, target = match.group("label"), check_url(match.group("target"))
            host = (urlsplit(target).hostname or "").lower().rstrip(".")
            if host in ("github.com", "www.github.com") and label.strip() != target:
                raise ValueError(f"El enlace de GitHub debe mostrar la URL exacta como texto: usa {target} en lugar de [{label}].")
            add(label, link=target)
        else:
            url = match.group("url")
            trailing = ""
            while url and url[-1] in ".,;:!?)]}'":
                if url[-1] == ")" and url.count("(") >= url.count(")"):
                    break
                trailing = url[-1] + trailing
                url = url[:-1]
            add(url, link=check_url(url))
            add(trailing)
    add(text[position:])
    return segments


def reference_key(value: str) -> str:
    """Orden alfabético en español: las tildes no envían «Álvarez» después de la Z."""
    plain = "".join(segment["text"] for segment in parse_inline(value))
    decomposed = unicodedata.normalize("NFD", plain)
    return "".join(character for character in decomposed if not unicodedata.combining(character)).casefold()


MAX_FIGURE_HEIGHT_CM = 20.0


def figure_size_cm(path, width_cm: float | None) -> tuple[float, float]:
    """Ancho y alto en cm: el ancho pedido, reducido si la figura no cabe en la altura de la página."""
    from PIL import Image

    with Image.open(path) as image:
        ratio = image.height / image.width
    width = width_cm or 14.0
    if width * ratio > MAX_FIGURE_HEIGHT_CM:
        width = MAX_FIGURE_HEIGHT_CM / ratio
    return width, width * ratio


Text = Annotated[str, Field(min_length=1, max_length=20_000)]
ShortText = Annotated[str, Field(min_length=1, max_length=300)]


class Block(BaseModel):
    """Un bloque del desarrollo. El texto admite **negrita**, *cursiva*, [texto](url) y URLs sueltas."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["heading", "paragraph", "bullets", "numbered", "quote", "table", "figure", "code", "page_break"]
    text: Text | None = Field(None, description="heading/paragraph/quote/code. Una línea en blanco separa párrafos.")
    level: Literal[1, 2, 3] | None = Field(None, description="Nivel APA del heading: 1 centrado, 2 y 3 a la izquierda.")
    items: list[Text] | None = Field(None, max_length=100, description="Elementos de bullets/numbered.")
    title: ShortText | None = Field(None, description="Título de table o figure (se numeran solos).")
    rows: list[list[Annotated[str, Field(max_length=2_000)]]] | None = Field(
        None, max_length=200, description="table: la primera fila es el encabezado; todas con igual número de columnas.")
    path: str | None = Field(None, max_length=4096, description="figure: ruta absoluta de una imagen PNG o JPEG.")
    width_cm: float | None = Field(None, ge=2, le=16.5, description="figure: ancho en cm (14 por defecto).")
    note: Annotated[str, Field(max_length=1_000)] | None = Field(None, description="Nota APA bajo table o figure.")

    @field_validator("text", "title", "note")
    @classmethod
    def _clean(cls, value):
        return clean_text(value) if isinstance(value, str) else value

    @field_validator("items")
    @classmethod
    def _clean_items(cls, value):
        return [clean_text(item) for item in value] if value is not None else value

    @field_validator("rows")
    @classmethod
    def _clean_rows(cls, value):
        return [[clean_text(cell) for cell in row] for row in value] if value is not None else value

    @model_validator(mode="after")
    def _required(self):
        need = {"heading": ("text", "level"), "paragraph": ("text",), "quote": ("text",), "code": ("text",),
                "bullets": ("items",), "numbered": ("items",), "table": ("title", "rows"),
                "figure": ("title", "path"), "page_break": ()}[self.type]
        missing = [name for name in need if getattr(self, name) in (None, [], "")]
        if missing:
            raise ValueError(f"El bloque {self.type} necesita: {', '.join(missing)}.")
        if self.type == "table":
            widths = {len(row) for row in self.rows}
            if len(self.rows) < 2 or widths == {0} or len(widths) != 1 or max(widths) > 12:
                raise ValueError("La tabla necesita encabezado y al menos una fila, todas con 1 a 12 columnas iguales.")
        if self.type != "code":
            for value in [self.text, self.title, self.note, *(self.items or []), *(c for r in self.rows or [] for c in r)]:
                if value:
                    parse_inline(value)
        return self


class DeliveryDocument(BaseModel):
    """Desarrollo del informe. El servidor añade la portada ULEAM, el título en la página 2 y las referencias."""

    model_config = ConfigDict(extra="forbid")

    title: ShortText = Field(description="Título del trabajo; aparece en la portada y al inicio del desarrollo.")
    blocks: list[Block] = Field(min_length=1, max_length=800)
    references: list[Text] = Field(default_factory=list, max_length=300,
                                   description="Referencias APA verificadas; se ordenan y van en una hoja aparte. Vacío si la tarea no lleva bibliografía.")

    @field_validator("title")
    @classmethod
    def _clean_title(cls, value):
        value = " ".join(clean_text(value).split())
        if not value:
            raise ValueError("El título está vacío.")
        return no_template_tokens(value)

    @field_validator("references")
    @classmethod
    def _clean_references(cls, value):
        cleaned = [" ".join(clean_text(item).split()) for item in value]
        for item in cleaned:
            parse_inline(item)
        return [item for item in cleaned if item]

    @model_validator(mode="after")
    def _limits(self):
        total = len(self.title) + sum(len(item) for item in self.references)
        figures = 0
        for block in self.blocks:
            total += sum(len(value or "") for value in (block.text, block.title, block.note))
            total += sum(len(item) for item in block.items or [])
            total += sum(len(cell) for row in block.rows or [] for cell in row)
            figures += block.type == "figure"
        if total > MAX_TOTAL_CHARACTERS:
            raise ValueError("El documento supera 400.000 caracteres.")
        if figures > 30:
            raise ValueError("El documento admite como máximo 30 figuras.")
        return self


CoverText = Annotated[str, Field(max_length=200)]


class CoverFields(BaseModel):
    """Datos de portada. Los estudiantes y la materia pueden venir del perfil verificado; no inventes docente, curso ni año."""

    model_config = ConfigDict(extra="forbid")

    materia: CoverText | None = None
    nombre_docente: CoverText | None = None
    estudiantes: list[CoverText] = Field(default_factory=list, max_length=MAX_STUDENTS,
                                         description="Integrantes del grupo, uno por elemento (1 a 6). Vacío: el estudiante del perfil.")
    carrera: CoverText | None = None
    curso: CoverText | None = Field(None, description="Curso o paralelo.")
    anio: CoverText | None = Field(None, description="Año o periodo académico.")

    @staticmethod
    def _clean(value):
        if isinstance(value, bool):
            raise ValueError("Se esperaba texto.")
        if isinstance(value, int):
            value = str(value)
        if isinstance(value, str):
            value = " ".join(clean_text(value).split())
            return no_template_tokens(value) or None
        return value

    @field_validator("materia", "nombre_docente", "carrera", "curso", "anio", mode="before")
    @classmethod
    def _text(cls, value):
        return cls._clean(value)

    @field_validator("estudiantes", mode="before")
    @classmethod
    def _students(cls, value):
        if value is None:
            return []
        if isinstance(value, str):
            value = [value]
        if not isinstance(value, list):
            raise ValueError("Se esperaba una lista de nombres.")
        names = [cls._clean(item) for item in value]
        return list(dict.fromkeys(name for name in names if name))
