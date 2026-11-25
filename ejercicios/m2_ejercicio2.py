# mi_servidor.py
import csv
from fastmcp import FastMCP

mcp = FastMCP("Ingesta de catalogo")

@mcp.tool()
def leer_lista_proveedor(archivo: str) -> list[dict]:
    """Lee el CSV de un proveedor y devuelve sus filas."""
    with open(archivo, encoding="utf-8") as f:
        return list(csv.DictReader(f))

@mcp.tool()
def buscar_en_catalogo(gtin: str) -> dict:
    """Busca un GTIN en catalogo_actual.csv y devuelve el producto si existe."""
    with open("catalogo/catalogo_actual.csv", encoding="utf-8") as f:
        for fila in csv.DictReader(f):
            if fila["gtin"] == gtin:  # ajustar al nombre real de la columna
                return fila
    return {"error": f"GTIN {gtin} no está en el catálogo"}

if __name__ == "__main__":
    mcp.run()