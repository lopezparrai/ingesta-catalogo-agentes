"""Compara resultados/consultas/respuestas.json con evals/consultas_esperado.json.
Mide: valor, productos citados, fuentes esperadas entre las citadas, y abstención donde corresponde.
Uso: py evaluar_consultas.py"""
import json
from pathlib import Path

RAIZ = Path(__file__).parent
resp = json.loads((RAIZ / "resultados" / "consultas" / "respuestas.json").read_text(encoding="utf-8"))["respuestas"]
esp = json.loads((RAIZ / "evals" / "consultas_esperado.json").read_text(encoding="utf-8"))


def clave(f):
    return (Path(f["archivo"]).name, f.get("pagina"), f.get("hoja"), f.get("fila"), f.get("linea"))


def valor_ok(e, r):
    if e is None:
        return True
    if r is None:
        return False
    try:
        return abs(float(str(r).split()[0].replace(",", ".")) - float(e)) < 0.01
    except ValueError:
        pass
    return str(e).lower() in str(r).lower()


def evaluar(e, r):
    res = r["respuesta"]
    if e["abstiene"]:
        return {"abstiene": bool(res.get("abstiene")) and res.get("valor") is None}
    out = {"valor": valor_ok(e["valor"], res.get("valor")) or valor_ok(e["valor"], res.get("texto"))}
    if e["items"] is not None and e["tipo"] not in ("conteo",):
        out["items"] = set(e["items"]) <= set(res.get("items", [])) and (
            e["tipo"] != "lista" or set(e["items"]) == set(res.get("items", [])))
    if e["fuentes"]:
        citadas = {clave(f) for f in res.get("fuentes", [])}
        out["fuentes"] = all(clave(f) in citadas for f in e["fuentes"])
    return out


filas = []
for r in resp:
    if "turnos" in r:
        for n, t in enumerate(r["turnos"]):
            filas.append((f"{r['id']}.{n + 1}", evaluar(esp["conversaciones"][r["id"]][n], t)))
    elif r["id"] in esp["consultas"]:
        filas.append((r["id"], evaluar(esp["consultas"][r["id"]], r)))
total = ok = 0
for i, m in filas:
    bien = all(m.values())
    total += 1
    ok += bien
    print(("OK    " if bien else "FALLA ") + i, "" if bien else {k: v for k, v in m.items() if not v})
print(f"\n{ok}/{total} respuestas con valor, productos y fuentes esperados")
sin = [k for k, v in esp["consultas"].items() if not v["verificado_a_mano"]] + [
    f"{c}.{n + 1}" for c, lista in esp["conversaciones"].items() for n, v in enumerate(lista) if not v["verificado_a_mano"]]
print(f"Atención: {len(sin)} casos del esperado sin verificar a mano: {sin}" if sin else "Todo el esperado está verificado a mano.")
