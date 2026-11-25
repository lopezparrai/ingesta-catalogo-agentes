# Dermalab (P05): qué dijo el PDF y qué cargó el sistema

Corrida única, sin ajustar el sistema antes: `py lote.py P05_Dermalab --modo tiempo-real`.

Fuente: `Dermalab_lanzamientos_2026.pdf`. En cada bloque el nombre va arriba y el código abajo.

| Código | Nombre en el PDF | Contenido | Nombre que cargó el sistema | Estado | Motivos |
|---|---|---|---|---|---|
| DL-151 | Dermalab Hydra Plus | 50 ml | GEL LIMPIADOR DERMALAB PURIFY X 50 ML | a_revision | gtin_faltante, dato_obligatorio_faltante |
| DL-103 | Dermalab Purify | 300 ml | PROTECTOR SOLAR DERMALAB SUN FPS 50+ X 300 ML | a_revision | gtin_faltante, dato_obligatorio_faltante |
| DL-106 | Dermalab Sun SPF 50+ | 50 ml | CREMA DERMALAB UREA 10 % X 50 ML | a_revision | gtin_faltante, dato_obligatorio_faltante |
| DL-109 | Dermalab Urea 10 % | 400 ml | SERUM DERMALAB LIFT X 400 ML | lista_para_alta | — |
| DL-112 | Dermalab Lift | 30 ml | CREMA DERMALAB HYDRA PLUS FPS 30 X 30 ML | lista_para_alta | — |
| DL-115 | Dermalab Hydra Plus SPF 30 | 50 ml | GEL LIMPIADOR DERMALAB PURIFY X 50 ML | lista_para_alta | — |
| DL-118 | Dermalab Purify | 150 ml | PROTECTOR SOLAR DERMALAB SUN FPS 30 X 150 ML | lista_para_alta | — |
| DL-121 | Dermalab Sun SPF 30 | 200 ml | SERUM DERMALAB LIFT NOCHE X 200 ML | lista_para_alta | — |
| DL-124 | Dermalab Lift Noche | 30 ml | PROTECTOR SOLAR DERMALAB SUN FPS 50 X 30 ML | lista_para_alta | — |
| DL-127 | Dermalab Sun SPF 50 | 200 ml | AGUA MICELAR DERMALAB SENSITIVE X 200 ML | lista_para_alta | — |
| DL-154 | Dermalab Sensitive | 400 ml | CREMA DERMALAB CLEAR X 400 ML | a_revision | gtin_faltante, dato_obligatorio_faltante |
| DL-130 | Dermalab Clear | 40 ml | PROTECTOR SOLAR DERMALAB FPS 30 X 40 ML | lista_para_alta | — |
| DL-133 | Dermalab Sun SPF 30 | 50 ml | PROTECTOR SOLAR DERMALAB KIDS FPS 50+ X 50 ML | lista_para_alta | — |
| DL-136 | Dermalab Sun Kids SPF 50+ | 200 ml | GEL DERMALAB AFTER SUN X 200 ML | lista_para_alta | — |
| DL-139 | Dermalab Sun After Sun | 200 ml | PROTECTOR SOLAR DERMALAB FPS 50 X 200 ML | lista_para_alta | — |
| DL-142 | Dermalab Sun SPF 50 | 50 ml | AGUA MICELAR DERMALAB SENSITIVE X 50 ML | lista_para_alta | — |
| DL-145 | Dermalab Sensitive | 200 ml | CREMA DERMALAB UREA 10 % X 200 ML | lista_para_alta | — |
| DL-148 | Dermalab Urea 10 % | 200 ml | (vacío) | a_revision | dato_obligatorio_faltante |

Resultado: los 18 nombres no coinciden con el del PDF (cada código recibió el nombre del bloque siguiente; DL-148,
el último, quedó sin nombre). El contenido, el EAN y el precio sí coinciden con el Excel y con el PDF.
Los códigos DL-103, DL-106, DL-151 y DL-154 no están en la lista de precios: su revisión por falta de EAN y costo es correcta.
