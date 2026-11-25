"""M6 — Esquema de la salida: la ficha sale estructurada y validada contra el estándar.

Un solo lugar define cómo es un resultado válido (tipos, listas cerradas del vocabulario, categorías de la
taxonomía, forma de cada fuente). Lo usan:
  - el hook `hook_esquema` (nucleo.py): frena `registrar_ficha` con el error por campo, que el modelo recibe
    como error de tool y corrige;
  - `schema_ficha()`: el mismo esquema, como JSON Schema con enums, para la tool `registrar_ficha`;
  - los tests (`prueba_hooks.py`) y la revisión de salidas ya generadas.

pydantic valida lo que el JSON Schema no puede expresar (una fuente es exactamente una de tres formas,
las claves de `fuentes` tienen que ser campos de la ficha).
"""
import csv
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError, field_validator, model_validator

ESTANDAR = Path(__file__).parent / "data" / "estandar"

_VOCAB = yaml.safe_load((ESTANDAR / "vocabulario.yaml").read_text(encoding="utf-8-sig"))
TIPOS = sorted({t for lista in _VOCAB["tipos"].values() for t in lista})
UNIDADES = list(_VOCAB["unidades"])
MONEDAS = list(_VOCAB["monedas"])
CONDICIONES = list(_VOCAB["condicion_venta"])
PELIGROS = list(_VOCAB["peligro_deposito"])
MOTIVOS = list(_VOCAB["motivos_revision"])
ESTADOS = list(_VOCAB["estados"])
with open(ESTANDAR / "taxonomia.csv", encoding="utf-8-sig", newline="") as _f:
    CATEGORIAS = sorted({f["codigo"].strip() for f in csv.DictReader(_f) if f.get("codigo")})

# campo -> valores permitidos (None siempre vale: un campo sin dato queda vacío, no se inventa)
LISTAS_CERRADAS = {
    "tipo": TIPOS, "unidad": UNIDADES, "moneda": MONEDAS, "condicion_venta": CONDICIONES,
    "peligro_deposito": PELIGROS, "categoria": CATEGORIAS,
}


def _entero(v):
    """Un entero de verdad: 400 vale, 400.0 también (JSON no distingue), 400.5 y True no."""
    if isinstance(v, bool):
        raise ValueError("tiene que ser un entero, no un booleano")
    if isinstance(v, float) and v.is_integer():
        return int(v)
    if not isinstance(v, int):
        raise ValueError(f"tiene que ser un entero, vino {v!r}")
    if v < 1:
        raise ValueError(f"tiene que ser un entero positivo, vino {v}")
    return v


class Ficha(BaseModel):
    """Los campos de ficha_de_producto.md (sección 1) más los de la FDS (sección 9). Nada más."""
    model_config = ConfigDict(extra="forbid")

    gtin: str | None = None
    descripcion: str | None = None
    marca: str | None = None
    tipo: str | None = None
    variante: str | None = None
    contenido: int | None = None
    unidad: str | None = None
    unidades_por_envase: int | None = None
    principio_activo: str | None = None
    concentracion: str | None = None
    condicion_venta: str | None = None
    categoria: str | None = None
    precio_costo: float | None = None
    moneda: str | None = None
    proveedor_id: str | None = None
    codigo_proveedor: str | None = None
    peligro_deposito: str | None = None
    numero_onu: str | None = None

    @field_validator("contenido", "unidades_por_envase", mode="before")
    @classmethod
    def _enteros(cls, v):
        return None if v is None else _entero(v)

    @field_validator("precio_costo", mode="before")
    @classmethod
    def _precio(cls, v):
        if v is None:
            return None
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise ValueError(f"tiene que ser un número, vino {v!r} (el decimal va con punto)")
        if v <= 0:
            raise ValueError("tiene que ser mayor que cero")
        return v

    @field_validator("gtin", "numero_onu", mode="before")
    @classmethod
    def _solo_digitos_en_texto(cls, v):
        if v is None:
            return None
        if not isinstance(v, str):
            raise ValueError(f"tiene que ir como texto (string), vino {type(v).__name__}")
        if v.strip() and not v.strip().isdigit():
            raise ValueError(f"tiene que tener solo dígitos, vino {v!r}")
        return v

    @model_validator(mode="after")
    def _listas_cerradas(self):
        for campo, permitidos in LISTAS_CERRADAS.items():
            v = getattr(self, campo)
            if v is not None and v not in permitidos:
                raise ValueError(f"{campo}={v!r} está fuera de la lista cerrada del estándar")
        return self


class Fuente(BaseModel):
    """{archivo, pagina} | {archivo, hoja, fila} | {archivo, linea}: exactamente una de las tres."""
    model_config = ConfigDict(extra="forbid")

    archivo: str
    pagina: int | None = None
    hoja: str | None = None
    fila: int | None = None
    linea: int | None = None

    @model_validator(mode="after")
    def _una_forma(self):
        if not self.archivo.strip():
            raise ValueError("archivo vacío")
        pdf = self.pagina is not None
        excel = self.hoja is not None or self.fila is not None
        csv_ = self.linea is not None
        if pdf + excel + csv_ != 1:
            raise ValueError("la fuente es {archivo, pagina} o {archivo, hoja, fila} o {archivo, linea}")
        if excel and (self.hoja is None or self.fila is None):
            raise ValueError("una fuente de Excel lleva hoja y fila")
        return self


class Resultado(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item_id: str
    estado: Literal[tuple(ESTADOS)]  # type: ignore[valid-type]
    duplicado_de: str | None
    motivos_revision: list[Literal[tuple(MOTIVOS)]]  # type: ignore[valid-type]
    ficha: Ficha
    fuentes: dict[str, Fuente | None]  # un campo sin dato puede venir con fuente null (= sin fuente)

    @field_validator("item_id")
    @classmethod
    def _formato_item_id(cls, v):
        proveedor, sep, codigo = v.partition(":")
        if not (sep and proveedor.startswith("P") and proveedor[1:].isdigit() and codigo.strip()):
            raise ValueError(f"item_id {v!r} tiene que ser <proveedor>:<código>, ej. P02:RIV-1236")
        return v

    @model_validator(mode="after")
    def _fuentes_de_campos_de_la_ficha(self):
        campos = set(Ficha.model_fields)
        raros = [c for c in self.fuentes if c not in campos]
        if raros:
            raise ValueError(f"fuentes de campos que no existen en la ficha: {raros}")
        return self


def errores_legibles(e: ValidationError, maximo: int = 8) -> str:
    """Un error por campo, con la ruta (ficha.contenido: ...), para que el modelo corrija todo junto."""
    partes = []
    for err in e.errors()[:maximo]:
        ruta = ".".join(str(p) for p in err["loc"])
        partes.append(f"{ruta}: {err['msg'].removeprefix('Value error, ')}")
    extra = len(e.errors()) - maximo
    return "; ".join(partes) + (f"; y {extra} error(es) más" if extra > 0 else "")


def validar_resultado(entrada: dict) -> str | None:
    """None si la entrada de registrar_ficha cumple el esquema; si no, el motivo para el modelo."""
    try:
        Resultado.model_validate(entrada)
    except ValidationError as e:
        return "La ficha no cumple el esquema: " + errores_legibles(e)
    return None


def schema_ficha() -> dict:
    """El objeto `ficha` de la tool registrar_ficha, con tipos y enums del estándar (guía al modelo)."""
    def texto(descr: str = "") -> dict:
        return {"type": ["string", "null"], "description": descr} if descr else {"type": ["string", "null"]}

    def enum(valores: list[str]) -> dict:
        return {"type": ["string", "null"], "enum": [*valores, None]}

    return {
        "type": "object",
        "description": "Los campos de ficha_de_producto.md. Sin dato: null. Nada fuera de esta lista.",
        "properties": {
            "gtin": texto("13 dígitos, como texto"),
            "descripcion": texto(), "marca": texto(), "tipo": enum(TIPOS), "variante": texto(),
            "contenido": {"type": ["integer", "null"]}, "unidad": enum(UNIDADES),
            "unidades_por_envase": {"type": ["integer", "null"]},
            "principio_activo": texto(), "concentracion": texto(), "condicion_venta": enum(CONDICIONES),
            "categoria": enum(CATEGORIAS), "precio_costo": {"type": ["number", "null"]},
            "moneda": enum(MONEDAS), "proveedor_id": texto(), "codigo_proveedor": texto(),
            "peligro_deposito": enum(PELIGROS), "numero_onu": texto("como texto, ej. 1950"),
        },
        "additionalProperties": False,
    }


if __name__ == "__main__":
    # Revisa las salidas ya generadas contra el esquema (sin API): py esquema.py
    import json
    import sys

    raiz = Path(__file__).parent
    total = malos = 0
    for ruta in sorted([*raiz.glob("salidas/*.json"), *raiz.glob("salidas_m*/*.json")]):
        if ruta.name.endswith(("_traza.json", "_extraccion.json")):
            continue
        for r in json.loads(ruta.read_text(encoding="utf-8")):
            total += 1
            motivo = validar_resultado(r)
            if motivo:
                malos += 1
                print(f"{ruta.parent.name}/{ruta.name} {r.get('item_id')}: {motivo[:300]}")
    print(f"\n{total - malos}/{total} registros cumplen el esquema")
    sys.exit(1 if malos else 0)
