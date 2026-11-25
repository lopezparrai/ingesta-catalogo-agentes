"""M5 — Prueba de los hooks y de los permisos, sin llamar a la API (corre en un segundo y no cuesta nada).

Toma una ficha real ya generada (lista_para_alta, de salidas/) y la rompe de a una cosa por vez: cada caso
tiene que ser frenado por el hook que corresponde, con el motivo que el modelo recibe como error.
Si un cambio al código o al criterio rompe un hook, esto falla antes de gastar un solo token.

Uso:  py prueba_hooks.py
"""
import copy
import json
import sys

import agente as A

SALIDAS = A.RAIZ / "salidas"


def ficha_valida() -> dict:
    """Una ficha lista_para_alta real, ya aceptada por los hooks cuando se generó."""
    for ruta in sorted(SALIDAS.glob("*.json")):
        if ruta.name.endswith("_traza.json"):
            continue
        for r in json.loads(ruta.read_text(encoding="utf-8")):
            if r["estado"] == "lista_para_alta" and not r["ficha"].get("peligro_deposito"):
                return r
    raise SystemExit("No encontré una ficha lista_para_alta en salidas/")


BASE = ficha_valida()


def variante(**cambios_ficha) -> dict:
    r = copy.deepcopy(BASE)
    r["ficha"].update(cambios_ficha)
    return r


def con_estado(estado: str, motivos: list[str]) -> dict:
    r = copy.deepcopy(BASE)
    r["estado"], r["motivos_revision"] = estado, motivos
    return r


def gtin_invalido() -> str:
    g = BASE["ficha"]["gtin"]
    ultimo = (int(g[-1]) + 1) % 10  # mismo GTIN con el dígito verificador cambiado
    return g[:-1] + str(ultimo)


# (descripción, agente, tool, entrada, ¿tiene que frenar?, hook esperado)
CASOS = [
    ("ficha válida real: pasa", "escritor", "registrar_ficha", BASE, False, None),
    ("lista_para_alta con GTIN de dígito verificador inválido", "escritor", "registrar_ficha",
     variante(gtin=gtin_invalido()), True, "hook_alta_valida"),
    ("lista_para_alta con GTIN de 12 dígitos (UPC sin el 0)", "escritor", "registrar_ficha",
     variante(gtin=BASE["ficha"]["gtin"][1:]), True, "hook_alta_valida"),
    ("lista_para_alta con moneda fuera del vocabulario", "escritor", "registrar_ficha",
     variante(moneda="DOLARES"), True, "hook_esquema"),
    ("lista_para_alta con tipo fuera del vocabulario", "escritor", "registrar_ficha",
     variante(tipo="COSA RARA"), True, "hook_esquema"),
    ("lista_para_alta con categoría que no es de la taxonomía", "escritor", "registrar_ficha",
     variante(categoria="INVENTADA"), True, "hook_esquema"),
    ("esquema: contenido decimal (400.5)", "escritor", "registrar_ficha",
     variante(contenido=400.5), True, "hook_esquema"),
    ("esquema: precio como texto con coma ('357,43')", "escritor", "registrar_ficha",
     variante(precio_costo="357,43"), True, "hook_esquema"),
    ("esquema: campo que no existe en la ficha", "escritor", "registrar_ficha",
     variante(color="ROJO"), True, "hook_esquema"),
    ("esquema: numero_onu como número en vez de texto", "escritor", "registrar_ficha",
     variante(numero_onu=1950), True, "hook_esquema"),
    ("esquema: valor fuera del vocabulario también en a_revision", "escritor", "registrar_ficha",
     {**con_estado("a_revision", ["dato_obligatorio_faltante"]), "ficha": {**BASE["ficha"], "tipo": "COSA RARA"}},
     True, "hook_esquema"),
    ("esquema: fuente sin página, hoja/fila ni línea", "escritor", "registrar_ficha",
     {**BASE, "fuentes": {**BASE["fuentes"], "precio_costo": {"archivo": "lista.pdf"}}}, True, "hook_esquema"),
    ("lista_para_alta con la descripción en minúsculas", "escritor", "registrar_ficha",
     variante(descripcion=BASE["ficha"]["descripcion"].lower()), True, "hook_alta_valida"),
    ("lista_para_alta sin precio (no se inventa)", "escritor", "registrar_ficha",
     variante(precio_costo=None), True, "hook_alta_valida"),
    ("a_revision sin ningún motivo", "escritor", "registrar_ficha",
     con_estado("a_revision", []), True, "hook_ficha_coherente"),
    ("motivo fuera del vocabulario", "escritor", "registrar_ficha",
     con_estado("a_revision", ["parece_raro"]), True, "hook_ficha_coherente"),
    ("duplicado sin el SKU del catálogo", "escritor", "registrar_ficha",
     con_estado("duplicado", []), True, "hook_ficha_coherente"),
    ("el extractor intenta registrar una ficha", "extractor", "registrar_ficha", BASE, True, "hook_permisos"),
    ("el escritor intenta leer un Excel del proveedor", "escritor", "leer_excel",
     {"archivo": "P01_Laboratorio_Andes/Actualizacion_precios_Andes.xlsx"}, True, "hook_permisos"),
    ("el extractor intenta buscar en el catálogo", "extractor", "buscar_en_catalogo",
     {"gtin": "7790000000000"}, True, "hook_permisos"),
]


def main() -> int:
    fallos = 0
    print(f"Ficha base: {BASE['item_id']}\n")
    for desc, agente, tool, entrada, debe_frenar, hook in CASOS:
        motivo = A.correr_hooks_antes(agente, tool, entrada)
        ok = (motivo is not None) == debe_frenar and (not debe_frenar or hook in (motivo or ""))
        fallos += not ok
        print(f"[{'OK ' if ok else 'FALLA'}] {desc}")
        if motivo:
            print(f"        frenó -> {motivo[:230]}")

    # Hook al terminar: ningún campo completado sin su fuente
    sin_fuente = copy.deepcopy(BASE)
    sin_fuente["fuentes"].pop("precio_costo", None)
    problemas = A.hook_al_terminar_fuentes({sin_fuente["item_id"]: sin_fuente})
    ok = bool(problemas) and "precio_costo" in problemas[0][1]
    fallos += not ok
    print(f"[{'OK ' if ok else 'FALLA'}] al terminar: precio_costo completado sin fuente")
    print(f"        frenó -> {problemas}")
    ok = A.hook_al_terminar_fuentes({BASE["item_id"]: BASE}) == []
    fallos += not ok
    print(f"[{'OK ' if ok else 'FALLA'}] al terminar: la ficha válida con todas sus fuentes pasa")

    print(f"\n{len(CASOS) + 2 - fallos}/{len(CASOS) + 2} casos como se esperaba")
    return 1 if fallos else 0


if __name__ == "__main__":
    sys.exit(main())
