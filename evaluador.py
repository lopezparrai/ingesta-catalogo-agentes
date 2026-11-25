"""Evaluador de fichas.

Compara lo que generó el agente (salidas/*.json) con fichas armadas y verificadas a mano
(evals/*_esperado.json). Mide ficha entera y fuente, y deja el acierto por campo como diagnóstico.

Uso:
    python evaluador.py [salida.json] [esperado.json]

Formato de cada caso esperado (el mismo que produce el agente):
    {"item_id": "P03:XXX", "estado": "...", "duplicado_de": null,
     "motivos_revision": [],            # para a_revision: no se compara el texto exacto
     "motivos_clave": ["gtin"],         # opcional: palabras que tienen que aparecer en los motivos
     "ficha": {...}, "fuentes": {"campo": {"archivo": "...", "linea": 5}},
     "ignorar": ["contenido"]}          # opcional: campos que no se evalúan en este caso

Fuentes: {"archivo", "linea"} (CSV), {"archivo", "hoja", "fila"} (Excel), {"archivo", "pagina"} (PDF).

Ejemplo con Andes:
    python evaluador.py salidas/P01_Laboratorio_Andes.json evals/andes_esperado.json
"""
import json
import sys
from collections import Counter
from pathlib import Path

RAIZ = Path(__file__).parent
SALIDA_DEFECTO = RAIZ / "salidas" / "litoral_altas_102026.json"
ESPERADO_DEFECTO = RAIZ / "evals" / "litoral_esperado.json"


def norm(v):
    """Vacío ('' / None) es lo mismo; strings sin espacios sobrantes; 5 == 5.0."""
    if v is None:
        return None
    if isinstance(v, str):
        v = v.strip()
        return v or None
    if isinstance(v, float) and v.is_integer():
        return int(v)
    return v


def norm_fuente(f):
    if not f:
        return None
    return {k: norm(Path(v).name if k == "archivo" and isinstance(v, str) else v) for k, v in f.items()}


def comparar(esp: dict, obt: dict) -> dict:
    """Devuelve {'ficha_ok', 'fuente_ok', 'errores', 'campos_mal'} para un producto."""
    errores, campos_mal = [], []

    if norm(esp["estado"]) != norm(obt.get("estado")):
        errores.append(f"estado: esperado {esp['estado']!r}, obtenido {obt.get('estado')!r}")
    if norm(esp.get("duplicado_de")) != norm(obt.get("duplicado_de")):
        errores.append(f"duplicado_de: esperado {esp.get('duplicado_de')!r}, obtenido {obt.get('duplicado_de')!r}")

    # Motivos: afirmar sobre propiedades, nunca igualdad exacta de strings
    motivos = obt.get("motivos_revision") or []
    if (esp["estado"] == "a_revision") != bool(motivos):
        errores.append("motivos_revision: debe haber motivo si y solo si el estado es a_revision")
    texto_motivos = " ".join(motivos).lower()
    for clave in esp.get("motivos_clave", []):
        if clave.lower() not in texto_motivos:
            errores.append(f"motivos_revision: no menciona {clave!r}")

    # Ficha: un campo esperado vacío que el agente completó cuenta como error
    f_esp, f_obt = esp.get("ficha", {}), obt.get("ficha", {})
    # 'ignorar': campos que el estándar no permite determinar en este caso (ej. un conflicto entre fuentes)
    ignorar = set(esp.get("ignorar", []))
    for campo in sorted((set(f_esp) | set(f_obt)) - ignorar):
        if norm(f_esp.get(campo)) != norm(f_obt.get(campo)):
            campos_mal.append(campo)
            errores.append(f"ficha.{campo}: esperado {f_esp.get(campo)!r}, obtenido {f_obt.get(campo)!r}")

    # Fuentes: archivo y línea/página/hoja+fila, para cada campo esperado con dato
    fuente_ok = True
    for campo, fuente in esp.get("fuentes", {}).items():
        if campo in ignorar:
            continue
        if norm_fuente(fuente) != norm_fuente(obt.get("fuentes", {}).get(campo)):
            fuente_ok = False
            errores.append(f"fuentes.{campo}: esperado {fuente}, obtenido {obt.get('fuentes', {}).get(campo)}")

    # La ficha cuenta como correcta si todo lo que no es fuente coincide; la fuente se mide aparte
    ficha_ok = not [e for e in errores if not e.startswith("fuentes.")]
    return {"ficha_ok": ficha_ok, "fuente_ok": fuente_ok, "errores": errores, "campos_mal": campos_mal}


def main(ruta_salida: Path, ruta_esperado: Path) -> None:
    if not ruta_esperado.exists():
        sys.exit(f"No encuentro {ruta_esperado}. Armá a mano las fichas esperadas (ver el docstring).")
    if not ruta_salida.exists():
        sys.exit(f"No encuentro {ruta_salida}. Corré antes: python agente.py <archivo del proveedor>")

    esperado = {x["item_id"]: x for x in json.loads(ruta_esperado.read_text(encoding="utf-8"))}
    obtenido = {x["item_id"]: x for x in json.loads(ruta_salida.read_text(encoding="utf-8"))}

    # Se evalúan los productos que el agente procesó (corre de a tandas); la cobertura se informa aparte
    procesados = [i for i in esperado if i in obtenido]
    n = len(procesados)
    if n == 0:
        sys.exit("El agente no devolvió ninguno de los productos esperados. Revisá el formato de item_id (P03:LT-XXXX).")
    fichas_ok = fuentes_ok = 0
    campos_mal = Counter()

    for item_id in procesados:
        esp = esperado[item_id]
        r = comparar(esp, obtenido[item_id])
        fichas_ok += r["ficha_ok"]
        fuentes_ok += r["fuente_ok"]
        campos_mal.update(r["campos_mal"])
        marca = "OK" if r["ficha_ok"] and r["fuente_ok"] else "FALLÓ"
        print(f"[{marca}] {item_id}")
        for e in r["errores"]:
            print(f"      - {e}")

    extra = set(obtenido) - set(esperado)
    if extra:
        print(f"\n(Productos devueltos que no están en el esperado, ignorados: {sorted(extra)})")

    print(f"\nCobertura:         {n}/{len(esperado)} productos esperados procesados")
    print(f"Acierto de ficha:  {fichas_ok}/{n} ({fichas_ok / n * 100:.0f}%)")
    print(f"Acierto de fuente: {fuentes_ok}/{n} ({fuentes_ok / n * 100:.0f}%)")
    if campos_mal:
        print("Campos que más fallan (diagnóstico):", dict(campos_mal.most_common(5)))


if __name__ == "__main__":
    main(
        Path(sys.argv[1]) if len(sys.argv) > 1 else SALIDA_DEFECTO,
        Path(sys.argv[2]) if len(sys.argv) > 2 else ESPERADO_DEFECTO,
    )