# Reto 2 · Modernizar el mantenimiento

| Entregable | Archivo |
|---|---|
| Problemas del `.bat`, ordenados por riesgo | Este documento, sección 1 |
| Script nuevo (PowerShell 5.1 y 7) | [src/Invoke-MantenimientoPortal.ps1](src/Invoke-MantenimientoPortal.ps1) y [src/MantenimientoPortal.psm1](src/MantenimientoPortal.psm1) |
| Registro de la tarea programada con una cuenta gMSA (sin contraseña) | [src/Register-TareaMantenimiento.ps1](src/Register-TareaMantenimiento.ps1) |
| Pruebas Pester (31, pasan en 5.1 y en 7) | [tests/MantenimientoPortal.Tests.ps1](tests/MantenimientoPortal.Tests.ps1) |
| Demostración reproducible y su evidencia | [demo/Invoke-Demo.ps1](demo/Invoke-Demo.ps1) → [evidencias/](evidencias/) |

## 1. Problemas de `mantenimiento_diario.bat`, ordenados por riesgo

| # | Riesgo | Problema | Línea | Qué puede pasar (o ya pasó) |
|---|---|---|---|---|
| 1 | **Crítico** | **Contraseña en texto plano** de una cuenta de dominio (`ANDINA\svc_mantenimiento`) | 31 | Cualquiera que lea el script o una copia de él (repositorios, backups, este kit) obtiene acceso al recurso de auditoría con esa cuenta. Además, la contraseña no se puede rotar sin editar el script |
| 2 | **Crítico** | **Siempre reporta éxito**: escribe "Proceso OK" y sale con `exit /b 0` sin revisar ningún paso | 35-36 | **Ya pasó.** Desde el 16/09 la ruta `D:\logs\iis` no existe, nada se limpia y el disco se llena (pronóstico del Reto 1: lleno el 22/09). La tarea programada sigue marcando "código 0" todos los días |
| 3 | **Crítico** | **`%1` sin validar** y rutas sin comillas | 8, 15, 18, 32 | Si se invoca sin argumento, la línea 18 se convierte en `del /q /s \*.tmp` y **borra todos los .tmp de la unidad**, de otras aplicaciones incluidas. Una ruta con espacios se parte en dos |
| 4 | **Alto** | **`iisreset` diario** "para liberar memoria" | 24 | Corta el servicio de **todos** los sitios cada noche y tumba las sesiones activas. Sobre todo, **ocultó la fuga de memoria** de la v2.3.1 hasta que estalló el viernes 18/09 (Reto 1) |
| 5 | **Alto** | **Borra todos los volcados de memoria** sin conservar ninguno | 21 | Destruye la evidencia para encontrar la causa de una caída. Encima la ruta está mal: Windows los escribe en `C:\CrashDumps`, así que los del 18/09 (unos 7 GB) se quedaron llenando el disco |
| 6 | **Alto** | **Borra logs antes de copiarlos a auditoría**, sin verificar la copia | 15 vs. 32 | Si la copia falla (red, permisos, share lleno), los logs de más de 7 días se pierden para siempre. Para una entidad financiera es un riesgo de cumplimiento |
| 7 | Medio | **Reinicia "Servicio Notificaciones" sin saber si hace falta** | 27-28 | Corta notificaciones en curso y, si el servicio se está cayendo (el Reto 1 muestra arranques frecuentes), lo esconde en vez de avisar |
| 8 | Medio | **Unidad fija `Z:`** con `net use` | 31-33 | Si `Z:` ya está en uso, la copia va a otro sitio o falla. Si `xcopy` falla, la unidad queda mapeada con la sesión de la cuenta |
| 9 | Medio | **`xcopy /s /y` copia todo cada noche**, sin comprobar nada | 32 | Tráfico y tiempo crecientes. Un archivo corrupto en auditoría nunca se repara |
| 10 | Medio | **Log inútil:** sin fecha, sin pasos, sin errores; el "Iniciando…" va a la consola y se pierde | 12, 35 | Imposible saber qué hizo y cuándo. `mantenimiento.log` tiene 30 líneas "Proceso OK" idénticas |
| 11 | Bajo | Sin control de ejecución simultánea, sin límite de tiempo y sin modo de prueba | — | Dos ejecuciones a la vez (tarea más una manual) compiten por los mismos archivos. No se puede probar sin hacer daño |
| 12 | Bajo | "Autor: soporte 2019 - no tocar, funciona" | 6 | Sin control de versiones ni dueño. Nadie lo revisó cuando cambió la infraestructura (retiro de D:, balanceador nuevo) |

## 2. Qué hace el script nuevo y qué desaparece

| Paso del `.bat` | Decisión | Reemplazo |
|---|---|---|
| 1. Borrar logs de más de 7 días | **Se mantiene, con salvaguardas** | Primero copia a auditoría y **verifica cada copia con SHA-256**. Solo borra lo que tiene copia verificada. Retención configurable (30 días por defecto, en lugar de 7). Si la carpeta no existe, **termina con código 2 sin tocar nada** |
| 2. Borrar `*.tmp` | **Se mantiene, acotado** | Solo en la carpeta temporal de la aplicación (`-RutaTemporales`), solo `.tmp` y solo si tienen más de 24 horas. Nunca recursivo sobre una ruta vacía |
| 3. Borrar todos los dumps | **Se reemplaza por retención** | Conserva siempre los 3 más recientes y borra los de más de 14 días. Además **avisa si hay dumps nuevos**: un dump nuevo es una caída del proceso, y alguien debe saberlo |
| 4. `iisreset` | **Desaparece** | Nada en el script. Corregir la fuga es tarea del equipo de desarrollo. Mientras tanto: <br>• reciclaje del pool **por memoria** configurado en IIS (`privateMemory`, por ejemplo 1 GB), que recicla un solo pool sin cortar las conexiones activas; <br>• monitoreo y auto-remediación con límites (Reto 3). <br>El script **informa** el estado y la memoria del pool para dejar la tendencia en el log |
| 5. Reiniciar Servicio Notificaciones | **Desaparece el reinicio** | El script verifica el servicio y **solo lo inicia si está detenido**, y lo deja registrado como advertencia. La recuperación automática se configura en el propio servicio (opciones de recuperación del SCM) y la caída se alerta desde Azure Monitor |
| 6. `net use` con contraseña y `xcopy` | **Desaparece** | Copia incremental y verificada. El acceso lo da la **identidad de la tarea programada (cuenta gMSA)**, cuya contraseña rota Windows y nadie conoce. Si hiciera falta otra identidad, se pasa `-Credencial` desde SecretManagement. A mediano plazo, la copia a auditoría se reemplaza por la recolección de Azure Monitor (Reto 3) hacia un almacenamiento inmutable |
| (nuevo) | **Se agrega** | Verificación de espacio libre en disco, estado del pool de IIS y su memoria, log estructurado y control de ejecución simultánea |

## 3. Requisitos de la prueba y cómo se cumplen

| Requisito | Cómo se cumple | Dónde se prueba |
|---|---|---|
| **Parámetros validados** | `Mandatory`, `ValidateNotNullOrEmpty` y `ValidateRange` en todos los parámetros. Las rutas se validan antes de hacer nada (código 2) | `termina con codigo 2 y no toca nada si la carpeta de logs no existe` |
| **Modo simulación** | `SupportsShouldProcess` en el script y en cada función que cambia algo. `-WhatIf` se pasa explícitamente al módulo, porque los módulos no lo heredan | 5 pruebas con `-WhatIf` y la ejecución 1 de la demo |
| **Código de salida confiable** | 0 = OK (las advertencias quedan en el log), 1 = algún paso falló, 2 = parámetros o precondiciones inválidos, 3 = otra ejecución en curso, 4 = error inesperado | Pruebas de códigos 0, 1, 2 y 3 ejecutando el script en un proceso aparte, como lo hace la tarea programada |
| **Log estructurado** | JSON Lines en UTF-8 sin BOM. Cada línea trae `ts`, `nivel`, `paso`, `mensaje`, `equipo`, `ejecucion` (GUID), `simulacion` y `datos`. Listo para ingerir en Log Analytics (Reto 3) | `escribe una linea JSON valida…`, `escribe UTF-8 sin BOM…` |
| **Ninguna credencial en el código** | Cuenta gMSA y `-Credencial` opcional. Una prueba analiza el código para confirmar que no hay contraseñas ni llamadas a `net` | `no contiene credenciales…` |
| **Ejecutable varias veces sin efectos no deseados** | La copia omite archivos idénticos (mismo hash), el borrado solo actúa sobre lo vencido, el servicio solo se inicia si está detenido y un mutex impide dos ejecuciones simultáneas | `es idempotente…` (3 pruebas) y la ejecución 3 de la demo |

## 4. Cómo reproducirlo

Pruebas, desde la raíz del repositorio (no requieren IIS ni ser administrador). En PowerShell 7:

```bash
pwsh -NoProfile -Command "Invoke-Pester ./reto2-powershell/tests -Output Detailed"
```

Y en Windows PowerShell 5.1:

```bash
powershell -NoProfile -ExecutionPolicy Bypass -Command "Invoke-Pester ./reto2-powershell/tests -Output Detailed"
```

Demostración sobre un servidor simulado en la carpeta temporal, usando los logs del kit:

```bash
powershell -NoProfile -ExecutionPolicy Bypass -File reto2-powershell/demo/Invoke-Demo.ps1
```

Resultado obtenido ([evidencias/demo_resumen.md](evidencias/demo_resumen.md)):

| Ejecución | Código | Logs IIS | En auditoría | Dumps | Temporales |
|---|---|---|---|---|---|
| 0. Estado inicial | — | 9 | 0 | 7 | 4 |
| 1. Simulación (`-WhatIf`) | 0 | 9 | 0 | 7 | 4 |
| 2. Ejecución real | 0 | 6 | 8 | 5 | 1 |
| 3. Repetición | 0 | 6 | 8 | 5 | 1 |

Cómo leer la tabla:
- La simulación no toca nada.
- La ejecución real archiva 8 logs (el del día en curso no, porque IIS lo tiene abierto) y borra los 3 de más de 30 días.
- Conserva los 5 dumps recientes, borra los 2 antiguos y **avisa** que hubo 5 caídas.
- Borra los 3 temporales viejos y deja el que está en uso.
- La repetición no cambia nada.

En el servidor (o en la VM del Reto 3), primero en simulación:

```bash
pwsh -File C:\scripts\Invoke-MantenimientoPortal.ps1 -RutaLogsIIS C:\inetpub\logs\LogFiles\W3SVC2 -RutaAuditoria \\fs-auditoria\logs$ -RutaTemporales C:\PortalPagos\temp -WhatIf
```

Después se registra la tarea con la cuenta gMSA (también tiene `-WhatIf`):

```bash
pwsh -File C:\scripts\Register-TareaMantenimiento.ps1 -CuentaGmsa 'ANDINA\gmsa-mantweb$' -RutaLogsIIS C:\inetpub\logs\LogFiles\W3SVC2 -RutaAuditoria \\fs-auditoria\logs$
```

## 5. Supuestos

| # | Supuesto |
|---|---|
| S1 | Los logs de IIS están ahora en `C:\inetpub\logs\LogFiles\W3SVC2` (evento del 16/09, línea 150) |
| S2 | La retención local de 30 días es suficiente porque auditoría conserva la copia. El valor lo debe confirmar el área de cumplimiento |
| S3 | Existe o se puede crear una cuenta gMSA con permiso de escritura en `\\fs-auditoria\logs$`. Si no, se usa `-Credencial` desde un almacén de secretos, nunca escrita en el script |
| S4 | La carpeta temporal de la aplicación se conoce y se pasa en `-RutaTemporales`. Sin ese parámetro el paso no se ejecuta, para no adivinar una ruta y borrar en el lugar equivocado |
| S5 | El script no reinicia el pool. Un reinicio con lógica de intentos, condiciones y escalamiento pertenece a la auto-remediación del Reto 3 |
