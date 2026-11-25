"""Ayuda para verificar a mano evals/consultas_esperado.json.
Muestra, por cada caso, la pregunta, lo que se espera y el DATO CRUDO de cada fuente esperada (leído del archivo
original). Vos comparás con tus ojos y respondés s (coincide), n (no) o Enter (saltear).
  py verificar_esperado.py              # interactivo: marca verificado_a_mano=true con 's'
  py verificar_esperado.py --imprimir   # solo imprime todo (para leer o guardar en un txt)
"""
import json
import sys
from pathlib import Path

import asistente as S

RUTA = Path(__file__).parent / "evals" / "consultas_esperado.json"
esp = json.loads(RUTA.read_text(encoding="utf-8"))
preg = json.loads(S.CONSULTAS.read_text(encoding="utf-8-sig"))
textos = {q["id"]: q["texto"] for q in preg["consultas"]}
turnos = {c["id"]: c["turnos"] for c in preg["conversaciones"]}
datos = S.Datos()


def mostrar(titulo: str, pregunta: str, e: dict) -> None:
    print("=" * 78)
    print(f"{titulo}: {pregunta}")
    print(f"  ESPERADO  valor={e['valor']!r}  abstiene={e['abstiene']}")
    if e.get("nota"):
        print(f"  NOTA      {e['nota']}")
    for i in (e["items"] or [])[:8]:
        f = datos.fichas.get(i)
        if f:
            fi = f["ficha"]
            print(f"  FICHA     {i}: {f['estado']} {f.get('motivos_revision') or ''} dup={f.get('duplicado_de')} | "
                  f"{fi.get('descripcion')} | costo={fi.get('precio_costo')} {fi.get('moneda')} | gtin={fi.get('gtin')} | "
                  f"peligro={fi.get('peligro_deposito')} | pack={fi.get('unidades_por_envase')}")
        else:
            print(f"  FICHA     {i}: (sin ficha)")
    if len(e["items"] or []) > 8:
        print(f"  ... y {len(e['items']) - 8} productos más")
    for fu in e["fuentes"]:
        r = datos.leer_fuente(**{k: v for k, v in fu.items()})
        print(f"  FUENTE    {fu}")
        print(f"            texto crudo: {str(r.get('texto', r))[:400]!r}")
        if r.get("titulos_de_la_hoja"):
            print(f"            títulos: {r['titulos_de_la_hoja']}")


casos = [(i, textos[i], e) for i, e in esp["consultas"].items()]
for c, lista in esp["conversaciones"].items():
    casos += [(f"{c}.{n + 1}", turnos[c][n], e) for n, e in enumerate(lista)]

imprimir = "--imprimir" in sys.argv
for titulo, pregunta, e in casos:
    if not imprimir and e["verificado_a_mano"]:
        continue
    mostrar(titulo, pregunta, e)
    if imprimir:
        continue
    r = input("¿Coincide con lo que dice el archivo? [s/n/Enter=saltear/q=salir] ").strip().lower()
    if r == "q":
        break
    if r == "s":
        e["verificado_a_mano"] = True
        RUTA.write_text(json.dumps(esp, ensure_ascii=False, indent=1), encoding="utf-8")
    elif r == "n":
        e["nota"] = ((e.get("nota") or "") + " REVISAR: no coincide.").strip()
        RUTA.write_text(json.dumps(esp, ensure_ascii=False, indent=1), encoding="utf-8")
print(f"\nVerificados: {sum(e['verificado_a_mano'] for _, _, e in casos)}/{len(casos)}")
