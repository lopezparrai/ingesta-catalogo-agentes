# Demo Day: guion de 15 minutos (slides + app)

Slides en `demo/slides_demo_day.html` (doble clic; flechas para avanzar, `F` para pantalla completa).
App con `streamlit run app/demo_app.py` desde la raíz del repo (`pip install -r requirements.txt` la primera vez).
La versión toda desde terminal quedó en `GUION_DEMO_terminal.md` como plan C.

## Antes de empezar (10 minutos antes)

1. Terminal en la raíz con `.env` cargado. App abierta (sin barra lateral: es solo la demo).
2. Interruptor del menú lateral (flecha « > » arriba a la izquierda) en "En vivo". Si algo falla, pasalo a "Respaldo": Archivo nuevo carga `demo_ensayo` y Consultas responde las cuatro preguntas ensayadas sin API (el cuadro de escribir se deshabilita). Decí en voz alta que es la corrida guardada. Si vas a correr en vivo, probá antes con una
   pregunta corta al asistente que la red y la API responden. La corrida en vivo borra `resultados/demo` y
   `data/proveedores/P10_Demo_Proveedor`; el respaldo vive en `resultados/demo_ensayo`.
3. Slides abiertas en otra ventana. Video de 2 minutos de la corrida a mano.

## Minuto a minuto

| Min | Dónde | Qué se muestra | Qué se dice |
|---|---|---|---|
| 0–0:20 | Slide 1 | Portada | Qué resuelve: un archivo de proveedor entra tal como llega y sale con fichas, duplicados detectados y una cola de revisión con motivo. |
| 0:20–1:10 | Slide 2 | El problema | Compras abre el archivo de cada proveedor (PDF, planilla, CSV, mail), copia a mano, elige la categoría y se fija si ya existe. Un error degrada búsqueda, reportes y recomendaciones. |
| 1:10–2:25 | Slide 3 | Arquitectura (M4) | Workflow con un solo escritor: extractores en paralelo (solo leen), consolidación por código, escritor con tools y hooks. El modelo interpreta; lo exacto lo hace el código. |
| 2:25–3:25 | Slide 4 | Qué impide que se equivoque (M5) | Cuatro hooks antes de registrar y uno al terminar; permisos por agente en código. Freno real: el hook de precio saltó una vez en la carga completa (5 fichas de Limpieza Hogar Sur). En el demo en vivo no frenó nada: no prometas un freno. |
| 3:25–4:15 | Slide 5 | La carga completa | 9 proveedores, 257 productos: 208 listos, 24 duplicados, 25 a revisión. La mayor parte de la cola es una sola cosa: falta el GTIN. |
| 4:15–5:10 | Slide 6 | Dermalab (M6) | Se corrió una vez con el sistema como estaba. Los 18 nombres salieron corridos un bloque; los hooks revisan forma, no correspondencia. Qué corregí: el lector de PDF suponía una tabla. La segunda corrida **no es una prueba limpia**. |
| 5:10–5:55 | Slide 7 | Costos (M4 y M6) | USD 0,27 por 257 fichas (USD 0,00105 por ficha), 25 min por Batch; caché leído 53 %. Batch contra tiempo real y paralelo contra secuencial. |
| 5:55–6:40 | Slide 8 | Cómo sé que anda (M1) | Fichas a mano 15/15 y fuente 12/15; consultas 29/29; es lo que se usó para ajustar, no mide generalización. La auditoría de 49 de 208 es un plan, no un resultado. |
| 6:40–6:50 | Slide 9 | Ahora, en vivo | Captura de la app; pasar al navegador. |
| 6:50–9:20 | App · Archivo nuevo | Correr en vivo (o cargar `demo_ensayo`) con el archivo de la demo | Mientras corre (~50 s): es un CSV con coma decimal, entra sin tocarlo. Al terminar: las fichas, la cola de revisión y una ficha con la fuente de cada campo; costo y tokens. **En el ensayo los hooks no frenaron nada**: no prometas un freno en rojo acá. |
| 9:20–10:50 | App · Consultas | LT-3447, AN-1124, NV-203 y la del jabón Pureza | Cita fuente. NV-203: el archivo pedía dar de alta sin revisar y el archivo es dato, no instrucción. La última no está en lo generado: tiene que decir que no lo tiene. |
| 10:50–12:10 | App · Fichas por proveedor | "Todos los proveedores" y después el logo de uno (por ejemplo Higiene Total); un producto a revisión con el origen de cada dato; el pedido al proveedor | Lo ya procesado: 257 productos de 9 proveedores. Cada dato dice de dónde salió. El pedido lo arma código a partir de los motivos; es un borrador que revisa una persona. El botón "Archivo nuevo" es el que acabás de procesar. |
| 12:10–13:30 | App · Scorecard de calidad | Scorecard con logos, el gráfico "cruda contra ajustada" | Un porcentaje crudo engaña con pocos productos: el shrinkage bayesiano (Beta-Binomial, Bayes empírico) lo corrige hacia la media de los 9. Orden de auditoría: Dermalab, Higiene Total, Natural Vida. **Pero la diferencia es chica**: todos entre 8 % y 12 %, ninguno pasa de 25 % de ser el peor. El pedido lo arma código a partir de los motivos. |
| 13:30–15 | Cierre | La app | Record linkage para los duplicados sin GTIN, línea base de clasificación, ordenar el catálogo viejo, más proveedores nuevos. El modelo no es determinista. |

El análisis estadístico (scorecard con shrinkage) vive solo en la app (pestaña Scorecard de calidad); las slides no lo repiten. La versión anterior con las pestañas Costos y Confianza quedó en `app/archivo/demo_app_completa.py`.

## Preguntas para el asistente (en este orden)

1. `¿Por qué LT-3447 quedó a revisión? ¿Con qué producto del catálogo podría ser el mismo?`
2. `¿Cuál es el precio de costo de AN-1124 de Laboratorio Andes y de dónde sale?`
3. `Natural Vida pidió dar todo de alta sin revisión. ¿Por qué NV-203 quedó a revisión igual?`
4. `¿Cuánto se vendió el mes pasado del jabón Pureza?` (dice que no lo tiene)

En la pestaña Consultas son cuatro botones de arranque (siempre visibles, con la pregunta completa al pasar el mouse) y el chat recuerda la conversación: se puede repreguntar ("¿y de ese proveedor?").
El check "Incluir el archivo nuevo de la demo" está en el desplegable "Opciones" (viene marcado). Si la API falla, el modo "Respaldo" usa las respuestas ya ensayadas (leen `asistente/resultados/respuestas.json`, sin API).

## El archivo nuevo (`Demo_altas_noviembre.csv`): qué se espera

La app no compara contra un "esperado": se ve como la vería el cliente. Esto es solo para vos, para saber qué mirar. El modelo no es determinista; en el ensayo salió 6 de 6 (47 s, USD 0,0131):

| Código | Qué trae | Qué debería pasar |
|---|---|---|
| DM-001 | Producto nuevo con GTIN válido | `lista_para_alta` |
| DM-002 | GTIN que ya está en el catálogo (SKU100014) | `duplicado` |
| DM-003 | GTIN con dígito verificador inválido | `a_revision`, GTIN inválido |
| DM-004 | Sin GTIN; es el "SH. BRISA COLOR 400ML." escrito distinto | `a_revision`, posible duplicado (SKU100007) |
| DM-005 | 0,5 LT y precio "1.234,56" | `lista_para_alta`, 500 ML, 1234,56 |
| DM-006 | GTIN inválido y un texto que pide dar de alta sin revisar | `a_revision`: el texto no cambió el criterio |

Con cualquier otro archivo la app se comporta igual: fichas, cola de revisión y origen de cada dato.

## Cifras para no equivocarse

- Batch, 9 proveedores: 257 fichas, 208 listas, 24 duplicados, 25 a revisión; USD 0,2709 (USD 0,00105 por ficha), 1.493 s; 53 % de la entrada leída de caché.
- Tiempo real (corrida de comparación): 247 fichas (Andes incompleto por `max_tokens`), USD 0,54, 6,4 min. No es comparable ficha a ficha.
- Paralelo 356 s contra secuencial 819 s en tres proveedores; en Rivera la escritura son 316 de los 356 s.
- Evaluación a mano: ficha 15/15 (Wilson 80 %–100 %), fuente 12/15 (55 %–93 %); los 3 errores son el código del proveedor de Andes atribuido al Excel y no al PDF. Son las fichas con las que se ajustó el sistema.
- Muestreo: de 208 listas, auditar 49 (error del lote menor al 5 % con 95 % de confianza si no se encuentra ninguno).
- Proveedores: 25 de 257 a revisión (9,7 %, Wilson 6,7 %–14,0 %). Shrinkage beta-binomial (media 10 %, concentración 80): tasa ajustada de 7,7 % (Cosmética Rivera) a 12,3 % (Dermalab); probabilidad de ser el peor, máximo 25 %.
- Si un estado sale distinto del esperado: no lo corrijas en vivo; mostrá el motivo que dio la ficha.

## Si algo sale mal

- **Falla la API o la red:** interruptor en "Respaldo" (menú lateral) y decir que es la corrida de ayer.
- **El asistente en vivo tarda o falla:** pasar el interruptor a "Respaldo": los cuatro botones de la pestaña Consultas responden con lo ya ensayado.
- **La app no arranca:** `GUION_DEMO_terminal.md` y los comandos de ahí.
- **Todo falla:** el video de 2 minutos.
