# Post-mortem: caída de PortalPagos del viernes 18 de septiembre de 2026

**Formato sin culpables.** Este documento busca entender qué falló en el sistema y en los procesos, no señalar personas. Todas las horas están en hora de Colombia.

## 1. Resumen en cinco líneas

1. El viernes 18/09, último día de un plazo de pago, PortalPagos se puso **lento desde las 11:30**, empezó a **fallar a las 13:23** y quedó **totalmente caído de 14:38 a 15:04**. Se recuperó al reiniciar el pool a mano.
2. La causa es una **fuga de memoria introducida en la versión 2.3.1** (desplegada el martes 15/09 en la noche). Cada pago confirmado deja en memoria unos 0,5 MB que nunca se liberan.
3. El reinicio automático de IIS de cada madrugada **escondía el problema**. El viernes hubo 2,3 veces más pagos que un día normal y la memoria se agotó a mitad de la tarde.
4. El NOC no lo vio porque **solo vigila que el servidor responda**, no que los clientes puedan pagar. Su sondeo respondió "OK" durante todo el periodo de errores.
5. **Hay un segundo riesgo activo y urgente:** el disco C: se está llenando y, al ritmo de un día hábil normal, **se agota el martes 22/09 hacia las 14:00**.

## 2. Impacto

| Indicador | Valor |
|---|---|
| Duración con afectación (lento y con errores) | 13:20 a 15:04, **1 h 44 min**; lentitud previa desde las 11:30 |
| Caída total (nadie podía entrar) | 14:38 a 15:04, **26 min** |
| Operaciones de clientes fallidas en el periodo | **1.593 de 3.620 (44 %)**, de ellas 504 intentos de iniciar o confirmar un pago |
| Clientes distintos que vieron un error | **Al menos 463** (solo se pueden contar quienes recibieron un error antes de la caída total) |
| Disponibilidad real del viernes | **94,2 %** de las operaciones y 92,7 % del tiempo |
| Disponibilidad real de la semana | **98,5 %** de las operaciones |
| Disponibilidad que reportó el NOC | "100 %". Su propio sondeo marcó 99,7 % (falló 52 veces, solo durante la caída total) |

## 3. Qué vieron los clientes, paso a paso

| Hora | Qué pasaba por dentro | Qué vivía el cliente |
|---|---|---|
| Mar 15/09, 22:03 | Se instala la versión 2.3.1: nuevo flujo de confirmación de pagos, una "caché de sesiones de pago" y registro de log en nivel de detalle máximo (Debug) | Nada |
| Mié 16/09, 11:30 | Se retira el disco D:. Los logs pasan a C:, pero el script nocturno sigue limpiando D: | Nada |
| Jue 17/09, 16:10 | La memoria ya llega a 1,2 GB al final del día | Ticket "portal lento en la tarde", cerrado como "no se reproduce" |
| Vie 18/09, 02:00 | Reinicio nocturno: la memoria vuelve a 300 MB | Nada |
| 11:30 | La memoria pasa de 1 GB y la respuesta se vuelve más lenta (p95 > 1 s, cuando lo normal es 0,7 s) | Páginas algo lentas |
| 12:40 | p95 > 3 s | Lentitud notoria al consultar y pagar |
| 13:23–13:24 | Primeros errores de "memoria insuficiente" al confirmar pagos | "Ha ocurrido un error inesperado". Primer ticket a las 13:34 |
| 13:20–14:38 | 1 de cada 5 operaciones falla y las lentas tardan 25 s | Pagos que no se confirman y reintentos |
| 14:22–14:38 | El proceso del portal se cae 5 veces seguidas. Windows lo deshabilita como protección | Conexiones cortadas |
| 14:38–15:04 | El servidor responde "Service Unavailable" a todo | Portal caído. Ticket crítico a las 14:42 |
| 15:04 | Reinicio manual del pool | Servicio restablecido |
| 16:37 | Windows avisa: "disco C: casi lleno" | Nada (todavía) |
| Dom 20/09 | Revisión semanal del NOC: "sin novedades" | — |

## 4. Por qué pasó

### Lo que está demostrado (hechos con evidencia)

| # | Hecho | Evidencia |
|---|---|---|
| H1 | Todos los errores del viernes fueron `OutOfMemoryException` dentro de `SesionPagoCache.Agregar`, al confirmar pagos | Eventos, líneas 304–346 (40 errores) y 347–368 (5 caídas del proceso) |
| H2 | Antes del despliegue la memoria del portal era estable (~310 MB). Desde el 16/09 crece cada día y solo baja con el reinicio de las 02:00 | Perfmon, `Process(w3wp)\Private Bytes`; figura 2 |
| H3 | La memoria crece **0,50 MB por cada pago confirmado**, con un ajuste casi perfecto (R² 0,999) e igual todos los días | `analisis.py`, modelo de memoria; figura 3 |
| H4 | El límite se alcanza con unas 2.370 confirmaciones sin reinicio. El viernes se llegó a 2.387 justo antes de la primera caída | Mismo modelo contra el log de IIS |
| H5 | Un día normal tiene unas 1.600 confirmaciones (68 % del límite) y el jueves tuvo 1.837 (78 %). El viernes, por el plazo de pago, tuvo 4.003 en el ciclo | Log de IIS |
| H6 | Tras 5 caídas en 16 minutos, Windows deshabilitó el pool (protección "Rapid-Fail") y todo respondió 503 hasta el reinicio manual | Eventos línea 366; `httperr1.log` líneas 5 a 1.545 |
| H7 | El sondeo `/health` del NOC respondió 200 OK en 156 de 156 intentos (en 4 ms) mientras los clientes tenían 19 % de errores y esperas de 25 s | Log de IIS, agente `NOC-HealthProbe` |
| H8 | Las alertas DCOM 10016 aparecen todos los días al mismo ritmo (26–53 por día), antes y después del incidente: **no tienen relación con la caída** | Tabla de eventos por día (`resultados.md`, sección 6) |

### Lo que es probable pero hay que confirmar (hipótesis)

| # | Hipótesis | Cómo confirmarla |
|---|---|---|
| P1 | La caché de sesiones de pago guarda cada sesión y nunca la expulsa (no tiene vencimiento ni límite de tamaño) | Revisar el código de `SesionPagoCache` de la v2.3.1 o analizar uno de los 5 volcados de memoria guardados en `C:\CrashDumps` |
| P2 | El proceso se quedó sin memoria con 1,5 GB aunque el servidor tenía 4,7 GB libres, posiblemente porque el pool corre en 32 bits o tiene un límite de memoria configurado | Revisar `applicationHost.config` (`enable32BitAppOnWin64`, `privateMemory`) |
| P3 | El NOC reporta "100 %" porque su herramienta redondea o exige varias fallas seguidas | Revisar la configuración del monitoreo del NOC |

### Factores que contribuyeron

- **El reinicio nocturno de IIS ocultó la fuga.** Cada madrugada "limpiaba" la memoria, así que el problema solo podía aparecer en un día con muchos pagos.
- **El despliegue no tuvo vigilancia posterior.** Nadie comparó memoria ni tiempos de respuesta antes y después de la v2.3.1.
- **El monitoreo mide lo que no importa.** Ping y `/health` confirman que el servidor está prendido, no que un cliente pueda pagar.
- **Las señales llegaron, pero no se conectaron.** El ticket de lentitud del jueves se cerró con "monitoreo en verde".
- **El incidente se cerró sin causa** y sin conservar evidencia. Por suerte los volcados de memoria siguen en el disco, porque el script los busca en otra carpeta (`C:\Dumps`).

## 5. ¿Se podía ver venir?

**Sí, desde el miércoles 16/09 a las 16:15**, unas 46 horas antes de la caída, cuando la memoria del portal superó por primera vez 900 MB:

| Indicador | Normal (antes de la v2.3.1) | Mié 16 | Jue 17 | Vie 18 |
|---|---|---|---|---|
| Memoria máxima del portal | 320 MB | 1.091 MB | 1.186 MB | 1.478 MB (caída) |
| Tiempo de respuesta p95 en la noche (19–23 h) | 0,6–0,7 s | 1,9 s | 2,1 s | — |
| Confirmaciones contra el límite de memoria | — | 68 % | 78 % | 169 % |

Una alerta sobre la memoria del proceso (por ejemplo, más de 900 MB) habría avisado el miércoles a media tarde. Una sobre el tiempo de respuesta, el miércoles en la noche. Con el calendario de pagos en la mano se podía anticipar que el viernes superaría el límite.

## 6. Otros riesgos encontrados

| Urgencia | Riesgo | Pronóstico y método |
|---|---|---|
| **Crítica (horas)** | **El disco C: se llena.** Desde la v2.3.1 el disco pierde **0,39 MB por cada operación de cliente**: 6,8 GB en un día hábil, 5 veces más que antes, probablemente por el log en nivel Debug. Además, el script ya no limpia nada porque sigue apuntando a D:, que no existe, y los 5 volcados del viernes ocupan ~7 GB. El domingo quedaban 10,9 GB libres de 119 GB | Regresión del consumo horario de disco contra las peticiones (R² 1,00), proyectada con el tráfico típico de cada hora. **Menos de 5 % libre el lunes 21/09 ~15:00 y disco lleno el martes 22/09 ~14:00.** Con tráfico alto, el martes ~07:00; con tráfico de fin de semana, el viernes 25/09 |
| **Alta (próximo día de pagos)** | **La caída se repetirá** cualquier día con más de ~2.370 pagos confirmados entre dos reinicios nocturnos. Un día normal ya está al 68 % del límite | Modelo de memoria (H3 y H4) |
| Alta | El script de mantenimiento tiene **una contraseña escrita en texto plano**, reinicia IIS todas las noches sin necesidad y **siempre reporta "OK"**, incluso cuando falla, como lleva haciendo desde el 16/09 | `mantenimiento_diario.bat`; la tarea programada termina con código 0 todos los días |
| Media | El 16/09 aparece un **balanceador o proxy nuevo** delante del servidor (cambia el formato del log), sin registro del cambio | `u_ex260917.log`, línea 2.351 |
| Media | El **Servicio Notificaciones** arranca de 3 a 8 veces por día sin que conste que se haya detenido: podría estar cayéndose y reiniciándose solo | Eventos 7036; falta exportar los eventos 7031/7034 |
| Baja | Escaneos automáticos de internet (`/.env`, `/wp-login.php`), unas 250 peticiones por día. Hoy no causan impacto | Log de IIS, agente `zgrab` |

## 7. Qué proponemos

**Hoy (contener):**
- Liberar espacio en C: con una copia previa de los volcados para el análisis.
- Bajar el log a nivel `Information`.
- Corregir la ruta de limpieza del script.

**Esta semana (que no se repita):**
- Corregir la caché, con vencimiento y límite de tamaño, y desplegarla con verificación posterior.
- Mientras tanto, programar un reciclaje del pool por memoria, por ejemplo a 1 GB, como mitigación temporal y documentada.

**Este mes (enterarnos antes que el cliente):**
- Monitorear lo que vive el cliente: tasa de errores, tiempo de respuesta, memoria, disco y estado del pool.
- Crear alertas con umbrales y una auto-remediación con límites (Reto 3).
- Reemplazar el script por uno que reporte la verdad (Reto 2).
- Revisar tableros después de cada despliegue.

*El código que respalda cada cifra está en `reto1-diagnostico/src/analisis.py`, y sus salidas en `reto1-diagnostico/salidas/`.*
