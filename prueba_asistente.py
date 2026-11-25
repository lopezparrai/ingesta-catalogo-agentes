"""Pruebas offline (sin API) de las tools y del hook de fuentes del asistente. Uso: py prueba_asistente.py"""
import asistente as S

d = S.Datos()
casos = []


def caso(nombre, ok):
    casos.append(ok)
    print(("OK   " if ok else "FALLA"), nombre)


r = d.buscar_fichas(proveedor="Limpieza Hogar Sur", peligro_deposito="corrosivo")
caso("conteo por código: corrosivos de LHS", r["total"] == len(r["fichas"]) and r["total"] > 0)
caso("proveedor por nombre parcial", S.resolver_proveedor("dermalab", d.proveedores) == "P05")
caso("proveedor desconocido avisa", "error" in d.buscar_fichas(proveedor="Inexistente"))
caso("item inexistente no inventa", d.buscar_fichas(item="ZZ-9999")["total"] == 0)
caso("item completo trae fuentes", "fuentes" in d.buscar_fichas(item="LT-3345")["fichas"][0])
r = d.buscar_codigo_en_archivos("HT32855")
caso("código en hoja de descontinuados", any(c["fuente"].get("hoja") == "Discontinuados" for c in r["coincidencias"]))
caso("leer_fuente CSV con encabezado", "encabezado" in d.leer_fuente("litoral_altas_102026.csv", linea=16))
caso("leer_fuente archivo inexistente", "error" in d.leer_fuente("nada.csv", linea=1))
caso("leer_fuente Excel pide hoja y fila", "error" in d.leer_fuente("HigieneTotal_novedades.xlsx"))

v = S.nueva_vistas()
S.juntar_vistas(v, d.buscar_fichas(item="LT-3345"))
f = {"archivo": "litoral_altas_102026.csv", "linea": 16}
caso("hook acepta fuente vista", S.hook_respuesta({"texto": "x", "items": ["P03:LT-3345"], "fuentes": [f]}, v)[0] is None)
caso("hook frena fuente inventada", S.hook_respuesta({"texto": "x", "fuentes": [{"archivo": "a.csv", "linea": 3}]}, v)[0] is not None)
caso("hook frena item inventado", S.hook_respuesta({"texto": "x", "items": ["P03:LT-0000"]}, v)[0] is not None)
caso("hook frena campo extra", S.hook_respuesta({"texto": "x", "otro": 1}, v)[0] is not None)
print(f"\n{sum(casos)}/{len(casos)}")
