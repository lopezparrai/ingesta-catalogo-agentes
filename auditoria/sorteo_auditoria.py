"""Auditoría por muestreo estratificado de las fichas listas para alta (sin API).

Las fichas listas para alta se cargan sin que nadie las mire, así que son las que se auditan. La muestra:
  - se estratifica por proveedor, porque los errores aparecen por formato de archivo y se concentran
    (Dermalab: todo un PDF);
  - se reparte en proporción al tamaño de cada proveedor, con un mínimo de 2 por proveedor;
  - tiene el tamaño mínimo que garantiza, con 95 % de confianza, que si no aparece ningún error el error del
    lote es menor al 5 %, AUN en el peor caso en que todos los errores estén en un mismo proveedor.
    (Sin estratos alcanzan 49; repartidas por proveedor, 49 bajan a 94 % en el peor caso.)

Regla de decisión: si la auditoría encuentra algún error, se audita completo el proveedor donde apareció.
La semilla es fija y se eligió antes de sortear: la muestra se puede reproducir y no se re-sortea.

Qué cuenta como error: la ficha entera (estado, duplicado_de, motivos y cada campo), igual que el evaluador.

Uso (desde la raíz del repo):
    python auditoria/sorteo_auditoria.py      # escribe auditoria/muestra_auditoria.csv
"""
from __future__ import annotations

import csv
import json
import random
import sys
from math import comb
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import comun as V   # noqa: E402

RAIZ = V.RAIZ
SEMILLA = 20261126          # fecha del Demo Day; fijada antes de sortear
CONFIANZA = 0.95
ERROR_MAXIMO = 0.05
MINIMO_POR_ESTRATO = 2
SALIDA = Path(__file__).resolve().parent / "muestra_auditoria.csv"


def asignar(n: int, tam: dict) -> dict:
    """Asignación proporcional (restos mayores) con un mínimo por estrato."""
    total = sum(tam.values())
    cuota = {k: n * v / total for k, v in tam.items()}
    a = {k: min(tam[k], max(MINIMO_POR_ESTRATO, int(cuota[k]))) for k in tam}
    for k in sorted(tam, key=lambda k: -(cuota[k] - int(cuota[k]))):
        if sum(a.values()) >= n:
            break
        if a[k] < tam[k]:
            a[k] += 1
    return a


def peor_caso(a: dict, tam: dict, d: int) -> float:
    """Máxima probabilidad de no ver ningún error, sobre todas las formas de repartir d errores entre estratos."""
    mejor = {0: 1.0}
    for k in tam:
        nuevo = {}
        for d0, p in mejor.items():
            for dh in range(0, min(tam[k], d - d0) + 1):
                q = comb(tam[k] - dh, a[k]) / comb(tam[k], a[k]) if tam[k] - dh >= a[k] else 0.0
                if p * q > nuevo.get(d0 + dh, -1.0):
                    nuevo[d0 + dh] = p * q
        mejor = nuevo
    return mejor.get(d, 0.0)


def tamano_muestra(tam: dict) -> tuple[int, dict, float]:
    total = sum(tam.values())
    d = int(ERROR_MAXIMO * total) + 1          # el menor número de errores que ya es "5 % o más"
    for n in range(1, total + 1):
        a = asignar(n, tam)
        p = peor_caso(a, tam, d)
        if p <= 1 - CONFIANZA:
            return sum(a.values()), a, p
    return total, dict(tam), 0.0


def nombres_proveedores() -> dict:
    with open(RAIZ / "data" / "proveedores" / "proveedores.csv", encoding="utf-8-sig", newline="") as fh:
        return {f["proveedor_id"]: f["nombre"] for f in csv.DictReader(fh)}


def taxonomia() -> dict:
    with open(RAIZ / "data" / "estandar" / "taxonomia.csv", encoding="utf-8-sig", newline="") as fh:
        return {f["codigo"]: f"{f['nivel_2']} › {f['nivel_3']}" for f in csv.DictReader(fh)}


def asi_vino(carpeta: str = "final") -> dict:
    """Lo que leyó el extractor, por item_id: 'archivo (fuente): campo=valor · ...'."""
    out: dict = {}
    for f in sorted((RAIZ / "resultados" / carpeta).glob("P*_extraccion.json")):
        for e in json.loads(f.read_text(encoding="utf-8")) or []:
            pid = str(e.get("archivo", ""))[:3]
            for fila in (e.get("datos") or {}).get("filas") or []:
                fu = fila.get("fuente") or {}
                donde = ", ".join(f"{k} {v}" for k, v in fu.items() if k != "archivo")
                campos = " · ".join(f"{k}={v}" for k, v in (fila.get("campos") or {}).items() if v not in (None, ""))
                out.setdefault(f"{pid}:{fila.get('codigo')}", []).append(f"{fu.get('archivo', '?')} ({donde}): {campos}")
    return out


def fuente_txt(f: dict | None) -> str:
    if not f:
        return ""
    return f.get("archivo", "?") + "".join(f" · {k} {v}" for k, v in f.items() if k != "archivo")


if __name__ == "__main__":
    fichas = [r for r in V.cargar("final") if r.get("estado") == "lista_para_alta"]
    por_prov: dict = {}
    for r in fichas:
        por_prov.setdefault(r["item_id"][:3], []).append(r)
    tam = {k: len(v) for k, v in sorted(por_prov.items())}
    n, asignacion, p = tamano_muestra(tam)

    rng = random.Random(SEMILLA)
    muestra = []
    for pid in sorted(por_prov):
        candidatos = sorted(por_prov[pid], key=lambda r: r["item_id"])
        muestra += rng.sample(candidatos, asignacion[pid])

    NOM, TAX, VINO = nombres_proveedores(), taxonomia(), asi_vino()
    columnas = ["N.º", "Proveedor", "Código", "Descripción", "Marca", "Tipo", "Variante", "Contenido", "Unidad",
                "Unidades por envase", "Concentración", "Categoría", "Categoría (nombre)", "Condición de venta", "GTIN",
                "Precio de costo", "Moneda", "Peligro en depósito", "Fuente (código)", "Así vino (lo que leyó el extractor)",
                "¿Ficha correcta? (Sí/No)", "Campo con error", "Comentario"]
    with open(SALIDA, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh, delimiter=";")
        w.writerow(columnas)
        for i, r in enumerate(muestra, 1):
            fi, fu = r.get("ficha") or {}, r.get("fuentes") or {}
            val = lambda k: "" if fi.get(k) is None else str(fi.get(k))
            w.writerow([i, NOM.get(r["item_id"][:3], r["item_id"][:3]), r["item_id"].split(":", 1)[1], val("descripcion"),
                        val("marca"), val("tipo"), val("variante"), val("contenido"), val("unidad"), val("unidades_por_envase"),
                        val("concentracion"), val("categoria"), TAX.get(fi.get("categoria"), ""), val("condicion_venta"),
                        val("gtin"), val("precio_costo"), val("moneda"), val("peligro_deposito"),
                        fuente_txt(fu.get("codigo_proveedor")), "\n".join(VINO.get(r["item_id"], [])), "", "", ""])

    print(f"Población: {sum(tam.values())} fichas listas para alta de {len(tam)} proveedores")
    print(f"Muestra: {n} fichas (semilla {SEMILLA}); peor caso de no ver errores si el lote tuviera 5 % o más: {p:.1%}")
    for pid in tam:
        print(f"  {pid} {NOM.get(pid, pid):<32} {tam[pid]:>3} listas -> {asignacion[pid]:>2} en la muestra")
    print(f"Escrito: {SALIDA.relative_to(RAIZ)}")
