"""Pedido al proveedor: el mensaje listo con lo que falta para cerrar sus revisiones.

Lo arma código, no un modelo: parte de los motivos de revisión que ya quedaron registrados en cada ficha
(estado "a_revision" + `motivos_revision`), agrupa por motivo y lista un producto por línea. Así el mensaje
solo menciona productos y motivos que existen en las fichas. Lo usa la app de la demo (app/demo_app.py).

Uso desde Python:
    from pedido_proveedor import mensaje_proveedor
    texto = mensaje_proveedor("Higiene Total S.A.", "HigieneTotal_novedades.xlsx", fichas_del_proveedor)
"""

PEDIDOS = {
    "gtin_faltante": "Código de barras (GTIN) de estos productos. Sin él no podemos confirmar si ya están en nuestro catálogo:",
    "gtin_invalido": "Revisar el código de barras de estos productos: el dígito verificador no es válido:",
    "dato_obligatorio_faltante": "Completar datos obligatorios que faltan en estos productos:",
    "conflicto_entre_fuentes": "Confirmar cuál de sus archivos rige: los datos de estos productos no coinciden entre sí:",
}


def mensaje_proveedor(nombre: str, archivos: str, fichas_prov: list[dict]) -> str:
    """Borrador del pedido al proveedor, armado por código a partir de los motivos (no lo redacta el modelo)."""
    def cod(x):
        return (x.get("ficha") or {}).get("codigo_proveedor") or x["item_id"].split(":", 1)[-1]
    grupos = {t: [] for t in PEDIDOS}
    for x in fichas_prov:
        if x.get("estado") != "a_revision":
            continue
        for m in x.get("motivos_revision") or []:
            if m in grupos:
                extra = f" (posible coincidencia con {x['duplicado_de']})" if m == "gtin_faltante" and x.get("duplicado_de") else ""
                grupos[m].append(cod(x) + extra)
    if not any(grupos.values()):
        return f"{nombre}: no hay productos a revisión. Nada para pedirle."
    lineas = [f"Hola, {nombre}:", "",
              f"Al cargar su archivo ({archivos}) quedaron productos que no pudimos dar de alta. Para cerrarlos necesitamos:", ""]
    for t, texto in PEDIDOS.items():
        if grupos[t]:
            lineas += [f"- {texto}", "  " + ", ".join(grupos[t])]
    lineas += ["", "Con eso los damos de alta. Gracias."]
    return "\n".join(lineas)
