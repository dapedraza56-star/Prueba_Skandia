# Reto 1 - Resultados generados por `analisis.py`

Todas las horas en hora de Colombia (UTC-5). Archivo generado: no editar a mano. Version visual: `reporte.html`.

| Indicador | Valor | Detalle |
|---|---|---|
| Disponibilidad real · viernes 18/09 | 94,2 % | 1.626 operaciones fallidas |
| Disponibilidad real · semana | 98,5 % | el NOC reportó 100 % |
| Portal caído | 26 min | 14:38 a 15:04 · con errores desde 13:23 |
| Disco C: lleno si no se actúa | mar 22/09 14:00 | quedan 10,9 GB · se consumen 6,8 GB/día |

## 1. Línea de tiempo del 18/09

Hora de Colombia. Cuándo empezó la degradación, el primer error, la caída y la recuperación, y qué vio el usuario en cada momento.

| Hora | Fase | Qué pasó | Qué vio el usuario | Evidencia |
|---|---|---|---|---|
| mar 15/09 22:03 | Antecedente | Despliegue PortalPagos v2.3.1: nuevo flujo de confirmación, caché de sesiones de pago y log en nivel Debug | Nada visible | eventos línea 109 |
| mié 16/09 11:30 | Antecedente | Se retira la unidad D:. Los logs pasan a C:, pero el .BAT sigue limpiando D:\logs\iis | Nada visible | eventos línea 150; mantenimiento_diario.bat |
| mié 16/09 22:12 | Antecedente | Aparece un balanceador/proxy delante del servidor (nuevo campo X-Forwarded-For; c-ip pasa a 10.20.4.4). No hay registro de ese cambio | Nada visible | u_ex260917.log línea 2351 |
| jue 17/09 16:10 | Señal ignorada | Ticket 'Portal de pagos lento en la tarde', cerrado con 'monitoreo en verde' | Lentitud | tickets T-10240 |
| vie 18/09 02:00 | Antecedente | iisreset nocturno: memoria de w3wp vuelve a ~300 MB | Nada visible | eventos línea 271 |
| vie 18/09 11:30 | Inicio de degradación | p95 de latencia supera 1,5x la línea base (700 ms) con memoria de w3wp en 1,089 MB | Páginas algo más lentas | u_ex260918.log; perfmon |
| vie 18/09 12:40 | Degradación fuerte | p95 > 3 s | Lentitud notoria al consultar y pagar | u_ex260918.log |
| vie 18/09 13:23 | Primer error | Primer 500 del incidente (/api/pagos/iniciar) | Error al pagar | u_ex260918.log línea 24018 |
| vie 18/09 13:24 | Primer error | Primera OutOfMemoryException en SesionPagoCache.Agregar (/api/pagos/confirmar) | 'Ha ocurrido un error inesperado' | eventos línea 304 |
| vie 18/09 14:22 | Caída | Primer crash de w3wp por OutOfMemory (se genera dump) | Conexiones cortadas | eventos líneas 347-350 |
| vie 18/09 14:34 | Caída | Crashes en cadena: 5 entre 14:22 y 14:38 | Errores intermitentes | eventos líneas 347, 352, 356, 360, 364 |
| vie 18/09 14:38 | Caída total | HTTP.sys responde 503 AppOffline a todo | Service Unavailable | httperr1.log línea 5 |
| vie 18/09 14:38 | Caída total | Rapid-Fail Protection deshabilita PortalPagosPool | Service Unavailable (503) | eventos línea 366 |
| vie 18/09 15:04 | Recuperación | Reinicio manual del pool | - | tickets T-10255 (sin evento) |
| dom 20/09 09:15 | Señal ignorada | Revisión semanal NOC: 'sin novedades', /health OK 100% | - | tickets T-10270 |

![fig1_incidente_18sep](fig1_incidente_18sep.png)

## 2. Causa raíz y factores contribuyentes

**Causa raíz:** una fuga de memoria introducida en la versión 2.3.1 (15/09 22:03). Cada pago confirmado deja memoria que nunca se libera; el viernes, con 2,3 veces más pagos, el proceso se quedó sin memoria a mitad de la tarde.

**Hechos (con evidencia)**

| Hecho | Evidencia |
|---|---|
| Todos los errores del viernes son OutOfMemoryException en SesionPagoCache.Agregar (confirmar pago) | eventos líneas 304-346 (40) y 347-368 (5 crashes) |
| La memoria del portal crece 0,50 MB por cada pago confirmado desde la v2.3.1 (R² 0,999); antes era estable en ~310 MB | Perfmon Private Bytes vs. log IIS · figura 3 |
| El límite se alcanza con ~2.369 pagos sin reinicio; el viernes cayó con 2.387 | modelo de memoria · log IIS |
| El viernes (fin de plazo) hubo 2,3 veces los pagos de un día normal | log IIS /api/pagos/confirmar |
| Tras 5 crashes en 16 min, Windows deshabilitó el pool y todo respondió 503 hasta el reinicio manual | eventos línea 366 · httperr1.log líneas 5-1545 |
| El reinicio nocturno de IIS (02:00) devolvía la memoria a 300 MB y ocultaba la fuga | eventos 3201/3202 diarios · figura 2 |
| DCOM 10016 aparece igual toda la semana: no tiene relación con la caída (ticket T-10261) | anexo B · eventos por día |

**Hipótesis (por confirmar)**

| Hipótesis | Cómo confirmarla |
|---|---|
| La caché guarda cada sesión de pago y nunca la expulsa (sin vencimiento ni tamaño máximo) | Revisar código de SesionPagoCache v2.3.1 o un dump de C:\CrashDumps |
| El proceso falla con ~1,5 GB aunque hay 4,7 GB libres: pool en 32 bits o con límite de memoria | Revisar applicationHost.config (enable32BitAppOnWin64, privateMemory) |
| El disco se consume por el log en nivel Debug activado en la v2.3.1 | Revisar tamaño de los logs de la aplicación en C: |

**Factores que contribuyeron**

- **Reinicio nocturno que oculta problemas:** la fuga solo podía estallar en un día de muchos pagos.
- **Despliegue sin verificación posterior:** nadie comparó memoria ni tiempos antes y después de la v2.3.1.
- **Monitoreo de infraestructura, no de cliente:** ping y /health dicen que el servidor está prendido, no que se pueda pagar.
- **Señales sin conectar:** el ticket de lentitud del jueves se cerró con «monitoreo en verde».

![fig3_fuga_memoria](fig3_fuga_memoria.png)

## 3. Disponibilidad real vs. lo que reporta el NOC

Disponibilidad real = operaciones de clientes sin error (sin archivos estáticos, sin el sondeo del NOC y sin escáneres). Incluye los 503 de la caída, que solo quedaron en el log de HTTP.sys.

| Día | Operaciones | Fallidas | Disponibilidad real (%) | Según sondeo del NOC (%) | Reportado por el NOC (%) |
|---|---|---|---|---|---|
| lun 14/09 | 17579 | 30 | 99.83 | 100.0 | 100 |
| mar 15/09 | 16567 | 21 | 99.87 | 100.0 | 100 |
| mié 16/09 | 17546 | 16 | 99.91 | 100.0 | 100 |
| jue 17/09 | 19455 | 26 | 99.87 | 100.0 | 100 |
| vie 18/09 | 28087 | 1626 | 94.21 | 98.19 | 100 |
| sáb 19/09 | 7809 | 5 | 99.94 | 100.0 | 100 |
| dom 20/09 | 4988 | 3 | 99.94 | 100.0 | 100 |
| Semana | 112031 | 1727 | 98.46 | 99.74 | 100 |

**¿Por qué no coincide?** El NOC solo mide ping y /health. Mientras los clientes tenían 19 % de errores y esperas de 25 s, /health respondió OK en 156 de 156 intentos: verifica que el servidor responde, no que se pueda pagar. Solo falló en los 26 min de caída total.

## 4. Señales tempranas: ¿se podía ver venir?

**Sí, desde el mié 16/09 a las 16:15** (unas 46 horas antes): la memoria del portal superó 900 MB por primera vez (antes del despliegue nunca pasaba de 320 MB). El jueves los pagos ya llegaban al 78 % del límite y la latencia nocturna se triplicó.

El disco del lunes y martes casi no baja porque el script todavía liberaba espacio cada noche; desde el 16/09 ya no (apunta a D:, que se retiró).

| Día | Memoria pico (MB) | Pagos vs. límite de memoria (%) | Latencia p95 19-23 h (s) | Disco consumido (GB) |
|---|---|---|---|---|
| lun 14/09 | 317 | 67 | 0.7 | nan |
| mar 15/09 | 320 | 65 | 0.6 | -0.2 |
| mié 16/09 | 1091 | 68 | 1.9 | 6.7 |
| jue 17/09 | 1186 | 78 | 2.1 | 7.5 |
| vie 18/09 | 1478 | 169 | 0.6 | 17.2 |
| sáb 19/09 | 995 | 30 | 1.2 | 3.0 |
| dom 20/09 | 644 | 17 | 0.5 | 1.9 |

![fig2_semana_memoria_disco](fig2_semana_memoria_disco.png)

## 5. Otros riesgos y pronóstico

| Urgencia | Riesgo | Detalle y pronóstico |
|---|---|---|
| Crítica | Disco C: se llena | 0,39 MB por operación desde la v2,3,1 y el ,BAT ya no limpia (apunta a D:), Lleno el mar 22/09 14:00 con tráfico normal; mar 22/09 07:00 con tráfico alto |
| Alta | La caída se repite | Cualquier día con más de ~2.369 pagos entre reinicios, Un día normal ya está al 68 % del límite |
| Alta | Script de mantenimiento inseguro | Contraseña en texto plano, iisreset diario innecesario y siempre reporta «OK» aunque falle |
| Media | Cambio no registrado | Aparece un balanceador delante del servidor el 16/09 (cambia el log) |
| Media | Servicio Notificaciones inestable | Arranca 3-8 veces por día sin registro de detención |
| Baja | Escaneos de internet | ~250 peticiones/día a /.env, /wp-login.php; hoy sin impacto |

**Pronóstico del disco C: (si no se hace nada)**

| Tráfico | Supuesto | GB por día | Libre < 5 % | Disco lleno |
|---|---|---|---|---|
| Bajo | como fin de semana | 2.4 | mié 23/09 02:00 | vie 25/09 12:00 |
| Normal | promedio lun-jue | 6.8 | lun 21/09 15:00 | mar 22/09 14:00 |
| Alto | como el viernes 18/09 | 10.3 | lun 21/09 12:00 | mar 22/09 07:00 |

Método: regresión del consumo horario de disco contra las operaciones (R² 1,00. 0,39 MB por operación). proyectada con el perfil horario observado de cada tipo de día, Cada crash adicional deja un dump de ~1.4 GB y adelanta la fecha,

## Anexo A · Calidad de los datos

| Tema | Hallazgo y tratamiento |
|---|---|
| Archivo duplicado | `u_ex260916 - copia.log` es identico (SHA-256) a `u_ex260916.log`; se carga una sola vez. |
| Zona horaria | IIS y HTTP.sys escriben en UTC: `u_ex260914.log` empieza a las 05:00 UTC (00:00 en Colombia) y `u_ex260921.log` solo llega a las 04:59 UTC. Se restan 5 h. Eventos y Perfmon ya estan en hora local. |
| Cambio de esquema W3C | `u_ex260917.log` cambia de campos en la linea 2351: se agregan `cs-host` y `X-Forwarded-For`. Desde ahi `c-ip` es el balanceador 10.20.4.4 y la IP real del cliente viene en `X-Forwarded-For`. |
| Huecos en Perfmon | 13 muestras sin valor de `Process(w3wp)\Private Bytes` (lineas 332, 364, 512, 813, 847, 884, 1330, 1331, 1332, 1333, 1334, 1535, 1618). Coinciden con momentos sin proceso w3wp (reinicios y la caida). Se tratan como nulos, no como cero. |
| Log del mantenimiento | `mantenimiento.log` tiene 30 lineas 'Proceso OK' sin fecha ni detalle; el .BAT lo escribe siempre, falle o no. No sirve como evidencia. |
| Eventos incompletos | La exportacion no tiene el evento del reinicio manual del pool a las 15:04 (solo consta en el ticket T-10255). Tampoco hay eventos 'stopped' del Servicio Notificaciones, solo 'running'. |
| Ruido | Sondeo del NOC (`NOC-HealthProbe`, 20101 peticiones) y escaneres (zgrab y rutas como /.env, 1772 peticiones) se excluyen del calculo de usuarios reales. |
| HTTP.sys | `httperr1.log` tiene 1541 respuestas 503 AppOffline que **no aparecen en el log de IIS**: si solo se mira IIS, la caida es invisible. |

## Anexo B · Eventos de Windows por día

| Evento | 14/09 | 15/09 | 16/09 | 17/09 | 18/09 | 19/09 | 20/09 |
|---|---|---|---|---|---|---|---|
| .NET crash w3wp | 0 | 0 | 0 | 0 | 5 | 0 | 0 |
| ASP.NET excepcion no manejada | 0 | 0 | 0 | 0 | 40 | 0 | 0 |
| DCOM 10016 (warning) | 30 | 38 | 53 | 44 | 43 | 27 | 26 |
| Disco casi lleno | 0 | 0 | 0 | 0 | 1 | 0 | 0 |
| Schannel TLS alerta 46 | 4 | 7 | 8 | 7 | 8 | 7 | 3 |
| Servicio Notificaciones 'running' | 3 | 3 | 3 | 8 | 5 | 3 | 7 |
| Tarea mantenimiento 'OK' | 1 | 1 | 1 | 1 | 1 | 1 | 1 |
| WAS pool deshabilitado | 0 | 0 | 0 | 0 | 1 | 0 | 0 |
| iisreset (stop) | 1 | 1 | 1 | 1 | 1 | 1 | 1 |
