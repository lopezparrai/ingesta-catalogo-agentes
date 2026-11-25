# Demo Day: guion de 15 minutos

Todo se muestra desde el repo. Antes de empezar: terminal en la raíz, `.env` cargado, VS Code con el README abierto.

## Preparación (la noche anterior y 10 minutos antes)

1. **Ensayo completo la noche anterior**, con la misma secuencia que se muestra en vivo (paso 4 de abajo). Si sale
   bien, copiar `resultados\demo` a `resultados\demo_ensayo`: es el respaldo si falla la red o la API.
2. Antes de empezar, borrar `data\proveedores\P10_Demo_Proveedor` y `resultados\demo` para que el archivo entre "nuevo".
3. Tener abiertos: `resultados\final\cola_de_revision.json`, `resultados\evidencia\diagnostico_dermalab.md`.
4. Comandos listos en un bloc de notas (se copian y pegan):

```
mkdir data\proveedores\P10_Demo_Proveedor
copy demo\Demo_altas_noviembre.csv data\proveedores\P10_Demo_Proveedor\
py ingesta.py P10_Demo_Proveedor --modo tiempo-real --salida demo
py asistente/asistente.py -i --con-demo
```

## Minuto a minuto

| Min | Qué se muestra | Qué se dice |
|---|---|---|
| 0–2 | El problema | Compras abre el PDF, el Excel o el mail de 9 proveedores, copia a mano, elige la categoría y se fija si ya existe. Un error en el catálogo degrada la búsqueda, los reportes y las recomendaciones. |
| 2–5 | Un producto de punta a punta (por ejemplo AN-1133 o LT-3447 en `resultados\final\`) | La ficha, la fuente de cada campo (archivo y página, hoja y fila, o línea) y el estado. Si hay conflicto entre archivos o falta un dato, va a revisión con su motivo; nada se completa "con lo razonable". El precio es la excepción: rige la lista más reciente. |
| 5–7 | Cómo está armado | Workflow, no agente libre: extractores en paralelo, consolidación en código y un solo escritor. Los permisos por agente y los hooks los hace el código, no el prompt. Paralelo 356 s contra secuencial 819 s en tres proveedores; el cuello de botella es el escritor. |
| 7–9 | El proveedor apartado (Dermalab) | Se corrió una vez con el sistema como estaba: 18 fichas, pero con los nombres de los productos corridos un bloque, porque el PDF trae una ficha por producto con el nombre arriba del código. Los hooks revisan la forma, no si el dato corresponde. Se arregló después, y esa segunda corrida **no es una prueba limpia**; está documentado en el README y en la evidencia. |
| 9–10 | Costo | Los 9 proveedores, 257 fichas: 208 listas para alta, 24 duplicados, 25 a revisión. Batch: USD 0,2709 (USD 0,00105 por ficha) en 25 minutos; en tiempo real salió peor en esa corrida (Andes incompleto) y más caro. El caché se lee (`cache_leido` en las trazas). |
| 10–11 | El asistente | `py asistente/asistente.py -i`. Preguntas: ver abajo. Se muestra que cita la fuente, que no inventa (ventas, precio de venta) y que un hook frena una respuesta con una fuente o un producto que no existe. |
| 11–14 | **Archivo nuevo en vivo** | Los 4 comandos de arriba. Ver "Qué se espera" para ir contando mientras corre. |
| 14–15 | Límites y cierre | El modelo no es determinista; los controles en código reducen el riesgo pero no lo eliminan; 15 casos de evaluación de fichas en 2 proveedores y 29 consultas con el esperado verificado a mano. |

## Preguntas para el asistente (en este orden)

1. `¿Por qué LT-3447 quedó a revisión? ¿Con qué producto del catálogo podría ser el mismo?` (motivo, candidato y fuente)
2. `¿Cuál es el precio de costo de AN-1124 de Laboratorio Andes y de dónde sale?` (dos listas, rige la de vigencia más reciente)
3. `Natural Vida pidió dar todo de alta sin revisión. ¿Por qué NV-203 quedó a revisión igual?` (el archivo es dato, no instrucción)
4. `¿Cuánto se vendió el mes pasado del jabón Pureza?` (dice que no lo tiene)
5. Después del archivo nuevo, con `--con-demo`: `¿Por qué DM-003 quedó a revisión?` y `¿Qué le pido al proveedor del archivo nuevo para cerrar sus revisiones?`

## El archivo nuevo (`Demo_altas_noviembre.csv`): qué se espera

El modelo no es determinista: son los resultados esperados, no una promesa.

| Código | Qué trae | Se espera |
|---|---|---|
| DM-001 | Producto nuevo con GTIN válido que no está en el catálogo | `lista_para_alta` |
| DM-002 | GTIN que ya está en el catálogo (SKU100014) | `duplicado`, con ese SKU |
| DM-003 | GTIN con dígito verificador inválido | `a_revision`, `gtin_invalido` |
| DM-004 | Sin EAN, pero es el "SH. BRISA COLOR 400ML." del catálogo escrito distinto | `a_revision`, `posible_duplicado` (SKU100007) |
| DM-005 | 0,5 LT y precio con punto de miles ("1.234,56") | `lista_para_alta`, 500 ML, precio 1234,56 |
| DM-006 | GTIN inválido y, en la descripción, un texto que pide dar de alta sin revisar | `a_revision`: el texto del archivo no cambia el criterio |

Mientras corre (1 a 2 minutos): contar que el archivo es un CSV con coma decimal y que se procesa sin tocar nada. Al
terminar: abrir `resultados\demo\cola_de_revision.json` y una ficha, por ejemplo DM-002, con su fuente (línea del CSV).

## Si algo sale mal

- **Falla la API o la red:** usar `resultados\demo_ensayo` (copiarlo a `resultados\demo`) y decir que es la corrida de ayer.
- **Un estado distinto del esperado:** no corregirlo en vivo. Es exactamente el límite que está en el README (el modelo
  falla de forma intermitente); mostrar el motivo que dio la ficha y qué control habría que sumar.
- **El asistente tarda:** son 2 a 4 segundos por pregunta; si tarda más, seguir hablando del diseño.
