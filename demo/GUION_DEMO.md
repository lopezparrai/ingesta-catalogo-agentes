# Demo Day: guion de 15 minutos (slides + app)

Slides en `demo/slides_demo_day.html` (doble clic; flechas para avanzar, `F` para pantalla completa).
App con `streamlit run app/demo_app.py` desde la raíz del repo (`pip install -r requirements.txt` la primera vez).
La versión toda desde terminal quedó en `GUION_DEMO_terminal.md` como plan C.

## Antes de empezar (10 minutos antes)

1. Terminal en la raíz con `.env` cargado. App abierta (sin barra lateral: es solo la demo).
2. Pestaña "Archivo nuevo" en modo "Cargar corrida guardada" con `demo_ensayo` (ya probado). Si vas a correr en vivo, probá antes con una
   pregunta corta al asistente que la red y la API responden. La corrida en vivo borra `resultados/demo` y
   `data/proveedores/P10_Demo_Proveedor`; el respaldo vive en `resultados/demo_ensayo`.
3. Slides abiertas en otra ventana. Video de 2 minutos de la corrida a mano.

## Minuto a minuto

| Min | Dónde | Qué se muestra | Qué se dice |
|---|---|---|---|
| 0–0:45 | Slide 1 | Portada | Qué resuelve: un archivo de proveedor entra tal como llega y sale con fichas, duplicados detectados y una cola de revisión con motivo. |
| 0:45–2 | Slide 2 | El problema | Compras abre el archivo de cada proveedor (PDF, planilla, CSV, mail), copia a mano, elige la categoría y se fija si ya existe. Un error degrada búsqueda, reportes y recomendaciones. |
| 2–3:30 | Slide 3 | Arquitectura | Workflow con un solo escritor. Tres decisiones: código para las cuentas, tools en vez de un prompt enorme, hooks y permisos en código. |
| 3:30–4:45 | Slide 4 | La carga completa | 9 proveedores, 257 productos: 208 listos, 24 duplicados, 25 a revisión. La mayor parte de la cola es una sola cosa: falta el EAN. |
| 4:45–6 | Slide 5 | Dermalab | Se corrió una vez con el sistema como estaba. Los 18 nombres salieron corridos un bloque; los hooks revisan forma, no correspondencia. La segunda corrida **no es una prueba limpia**. |
| 6–7:15 | Slide 6 | Costos | USD 0,27 por 257 fichas (USD 0,00105 por ficha), 25 min por Batch. El tiempo real fue más caro y quedó incompleto: sirve para costo y tiempo, no para calidad. |
| 7:15–8:15 | Slide 7 | Qué se puede afirmar | Ficha 15/15 y fuente 12/15 con sus intervalos; es lo que se usó para ajustar, no mide generalización. Plan de auditoría: 49 de 208. |
| 8:15–8:30 | Slide 8 | Ahora, en vivo | Pasar a la app. |
| 8:30–11 | App · Archivo nuevo | Correr en vivo (o cargar `demo_ensayo`) con el archivo de la demo | Mientras corre (~50 s): es un CSV con coma decimal, entra sin tocarlo. Al terminar: las fichas, la cola de revisión y una ficha con la fuente de cada campo; costo y tokens. **En el ensayo los hooks no frenaron nada**: no prometas un freno en rojo acá. |
| 11–12:15 | App · Consultas | LT-3447, AN-1124, NV-203 y la del jabón Pureza | Cita fuente. NV-203: el archivo pedía dar de alta sin revisar y el archivo es dato, no instrucción. La última no está en lo generado: tiene que decir que no lo tiene. |
| 12:15–14:45 | App · Calidad por proveedor | Logos y mapa de calor por tipo de problema, "¿Hay proveedores peores que otros?" y un pedido listo (por ejemplo Higiene Total) | No hay un proveedor peor en total (p = 0,10); por tipo de problema sí hay patrón (datos obligatorios faltantes, p ajustado 0,003). Para Compras: priorizar por tipo de problema, no por proveedor. El pedido lo arma código a partir de los motivos. |
| 14:45–15 | Cierre | Slide 8 o la app | Record linkage para los duplicados sin EAN, línea base de clasificación, ordenar el catálogo viejo, más proveedores nuevos. El modelo no es determinista. |

El análisis estadístico vive solo en la app (pestaña Calidad por proveedor); las slides no lo repiten. La versión anterior con las pestañas Costos y Confianza quedó en `app/archivo/demo_app_completa.py`.

## Preguntas para el asistente (en este orden)

1. `¿Por qué LT-3447 quedó a revisión? ¿Con qué producto del catálogo podría ser el mismo?`
2. `¿Cuál es el precio de costo de AN-1124 de Laboratorio Andes y de dónde sale?`
3. `Natural Vida pidió dar todo de alta sin revisión. ¿Por qué NV-203 quedó a revisión igual?`
4. `¿Cuánto se vendió el mes pasado del jabón Pureza?` (dice que no lo tiene)

En la pestaña Consultas son botones de arranque (aparecen mientras el chat está vacío) y el chat recuerda la conversación: se puede repreguntar ("¿y de ese proveedor?").
Marcá "Incluir lo procesado en `resultados/demo`" si corriste el archivo nuevo. Si la API falla, el desplegable "Respaldo" tiene las respuestas ya ensayadas (leen `asistente/resultados/respuestas.json`, sin API).

## El archivo nuevo (`Demo_altas_noviembre.csv`): qué se espera

La app no compara contra un "esperado": se ve como la vería el cliente. Esto es solo para vos, para saber qué mirar. El modelo no es determinista; en el ensayo salió 6 de 6 (47 s, USD 0,0131):

| Código | Qué trae | Qué debería pasar |
|---|---|---|
| DM-001 | Producto nuevo con GTIN válido | `lista_para_alta` |
| DM-002 | GTIN que ya está en el catálogo (SKU100014) | `duplicado` |
| DM-003 | GTIN con dígito verificador inválido | `a_revision`, EAN inválido |
| DM-004 | Sin EAN; es el "SH. BRISA COLOR 400ML." escrito distinto | `a_revision`, posible duplicado (SKU100007) |
| DM-005 | 0,5 LT y precio "1.234,56" | `lista_para_alta`, 500 ML, 1234,56 |
| DM-006 | GTIN inválido y un texto que pide dar de alta sin revisar | `a_revision`: el texto no cambió el criterio |

Con cualquier otro archivo la app se comporta igual: fichas, cola de revisión y origen de cada dato.

## Cifras para no equivocarse

- Batch, 9 proveedores: 257 fichas, 208 listas, 24 duplicados, 25 a revisión; USD 0,2709 (USD 0,00105 por ficha), 1.493 s; 53 % de la entrada leída de caché.
- Tiempo real (corrida de comparación): 247 fichas (Andes incompleto por `max_tokens`), USD 0,54, 6,4 min. No es comparable ficha a ficha.
- Paralelo 356 s contra secuencial 819 s en tres proveedores; en Rivera la escritura son 316 de los 356 s.
- Evaluación a mano: ficha 15/15 (Wilson 80 %–100 %), fuente 12/15 (55 %–93 %); los 3 errores son el código del proveedor de Andes atribuido al Excel y no al PDF. Son las fichas con las que se ajustó el sistema.
- Muestreo: de 208 listas, auditar 49 (error del lote menor al 5 % con 95 % de confianza si no se encuentra ninguno).
- Proveedores: 25 de 257 a revisión (9,7 %, Wilson 6,7 %–14,0 %). Total por proveedor: p = 0,10. Por tipo, con Holm: datos obligatorios faltantes 0,004; falta de EAN 0,06; conflicto entre archivos 0,08.
- Si un estado sale distinto del esperado: no lo corrijas en vivo; mostrá el motivo que dio la ficha.

## Si algo sale mal

- **Falla la API o la red:** "Cargar corrida guardada" con `demo_ensayo`, y decir que es la corrida de ayer.
- **El asistente en vivo tarda o falla:** usar el desplegable "Respaldo" de la pestaña Consultas.
- **La app no arranca:** `GUION_DEMO_terminal.md` y los comandos de ahí.
- **Todo falla:** el video de 2 minutos.
