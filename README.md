# Prueba técnica · Especialista en Observabilidad y Automatización

Solución al caso **PortalPagos** de Andina Financiera, una empresa ficticia con datos sintéticos.

## Estado de cada reto

| Reto | Carpeta | Estado |
|---|---|---|
| 1 · Diagnóstico basado en datos | [reto1-diagnostico/](reto1-diagnostico/) | ✅ Análisis reproducible, reporte visual, pruebas y post-mortem |
| 2 · Modernizar el mantenimiento | [reto2-powershell/](reto2-powershell/) | ✅ Script, 31 pruebas (PowerShell 5.1 y 7) y demo. Falta la evidencia en un servidor con IIS (depende del Reto 3) |
| 3 · Observabilidad y auto-remediación en Azure | — | ⏳ No se pudo activar la cuenta gratuita de Azure (ver "Supuestos"). La base de conexión está en el Reto 4 |
| 4 · IA para el triage de incidentes | [reto4-triage-ia/](reto4-triage-ia/) | 🟡 Componente, validación y 13 pruebas. Los casos con el modelo real requieren un token de GitHub Models |
| 5 · Propuesta de 90 días | [reto5-propuesta/](reto5-propuesta/) | ✅ PDF de 2 páginas |
| Bitácora de uso de IA | [IA_BITACORA.md](IA_BITACORA.md) | ✅ |

**Para leer sin ejecutar nada:**
- el post-mortem: [reto1-diagnostico/postmortem.md](reto1-diagnostico/postmortem.md);
- la propuesta: `reto5-propuesta/propuesta_90_dias.pdf`;
- el reporte visual del Reto 1: `reto1-diagnostico/salidas/reporte.html` (descárgalo y ábrelo con doble clic).

---

# Guía paso a paso para ejecutarlo

Esta guía no requiere conocimientos técnicos. Está pensada para **Windows 10 u 11**. Cada comando se copia y se pega tal cual en la ventana de PowerShell y se ejecuta con **Enter**. Al final de cada paso se indica **qué deberías ver**.

## Paso 0 · Preparar el equipo (una sola vez, unos 10 minutos)

**0.1 · Abrir PowerShell.** Pulsa la tecla **Windows**, escribe `PowerShell` y abre **Windows PowerShell**. No necesitas ser administrador.

**0.2 · Instalar los programas necesarios.** Si ya los tienes, omite este paso. Ejecuta estos comandos uno por uno. Cada uno puede tardar un par de minutos.

Python, para los Retos 1, 4 y 5:
```powershell
winget install --id Python.Python.3.12 -e
```

Git, para descargar el repositorio:
```powershell
winget install --id Git.Git -e
```

PowerShell 7, para el Reto 2. Es opcional, porque el Reto 2 también funciona con el PowerShell que trae Windows:
```powershell
winget install --id Microsoft.PowerShell -e
```

Pester, la herramienta de pruebas del Reto 2:
```powershell
Install-Module Pester -Scope CurrentUser -Force -SkipPublisherCheck
```

Si `Install-Module` pregunta si confías en el repositorio *PSGallery*, responde **S** (sí) o **A** (sí a todo).

Cuando termines, **cierra PowerShell y ábrelo de nuevo** para que reconozca los programas recién instalados.

**0.3 · Descargar el repositorio.** Con este comando se crea la carpeta `Prueba_Skandia` dentro de tu carpeta de usuario:
```powershell
git clone https://github.com/dapedraza56-star/Prueba_Skandia.git
```

Para entrar en ella:
```powershell
cd Prueba_Skandia
```

**Todos los pasos siguientes se ejecutan dentro de esta carpeta.** Si cierras PowerShell, vuelve a entrar con `cd Prueba_Skandia`.

**0.4 · Preparar Python para este proyecto.** Esto crea un espacio aislado (`.venv`) con las librerías del proyecto, sin tocar el resto de tu equipo:
```powershell
python -m venv .venv
```
```powershell
.venv\Scripts\python -m pip install -r requirements.txt
```

✔️ **Qué deberías ver:** varias líneas de instalación, sin la palabra `ERROR` al final.

---

## Reto 1 · Diagnóstico del incidente

**Qué hace:** lee los logs, eventos, métricas y tickets del kit, reconstruye lo que pasó el 18/09, calcula la disponibilidad real y los pronósticos, y genera un reporte visual.

**1.1 · Ejecutar el análisis** (unos 15 segundos):
```powershell
.venv\Scripts\python reto1-diagnostico\src\analisis.py
```

✔️ **Qué deberías ver:**
- un resumen corto en la ventana, con la disponibilidad del viernes (**94,2 %**), la de la semana (**98,5 %**), la caída de **26 min** y la fecha en que se llenaría el disco;
- **el reporte se abre solo en el navegador**. Si no se abre, búscalo en `reto1-diagnostico\salidas\reporte.html` y ábrelo con doble clic.

**1.2 · Ejecutar las pruebas automáticas:**
```powershell
.venv\Scripts\python -m pytest reto1-diagnostico\tests -v
```

✔️ **Qué deberías ver:** 4 líneas que terminan en `PASSED` y al final `4 passed`.

**Dónde quedan los resultados:** `reto1-diagnostico\salidas\` contiene el reporte, las tablas y las gráficas. El post-mortem es `reto1-diagnostico\postmortem.md`.

---

## Reto 2 · Script de mantenimiento en PowerShell

**Qué hace:** reemplaza el script `.bat` antiguo por uno en PowerShell que es seguro, se puede simular y deja registro de todo.

**2.1 · Ejecutar las pruebas automáticas** (unos 20 segundos). No necesita IIS ni permisos de administrador.

Con el PowerShell que trae Windows (5.1):
```powershell
powershell -NoProfile -ExecutionPolicy Bypass -Command "Invoke-Pester .\reto2-powershell\tests -Output Detailed"
```

Con PowerShell 7, si lo instalaste:
```powershell
pwsh -NoProfile -Command "Invoke-Pester .\reto2-powershell\tests -Output Detailed"
```

✔️ **Qué deberías ver:** una lista de pruebas en verde y al final `Tests Passed: 31, Failed: 0`. Los mensajes que empiezan con **"What If"** o **"Whatif"** son normales: los escriben las pruebas del modo simulación.

**2.2 · Ver una demostración.** El script arma un "servidor simulado" en una carpeta temporal y ejecuta el mantenimiento 3 veces: en simulación, de verdad y repitiéndolo.
```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\reto2-powershell\demo\Invoke-Demo.ps1
```

✔️ **Qué deberías ver:** una tabla como esta:

| Ejecución | Código | Logs IIS | En auditoría | Dumps | Temporales |
|---|---|---|---|---|---|
| 0. Estado inicial | - | 9 | 0 | 7 | 4 |
| 1. Simulación (-WhatIf) | 0 | 9 | 0 | 7 | 4 |
| 2. Ejecución real | 0 | 6 | 8 | 5 | 1 |
| 3. Repetición | 0 | 6 | 8 | 5 | 1 |

Cómo leerla: la simulación no cambia nada; la ejecución real archiva y luego limpia; repetirla no causa efectos nuevos. El detalle queda en `reto2-powershell\evidencias\`.

---

## Reto 3 · Observabilidad en Azure

No hay nada que ejecutar todavía (ver "Supuestos"). La conexión prevista con el Reto 4 está documentada en [reto4-triage-ia/README.md](reto4-triage-ia/README.md), sección 6.

---

## Reto 4 · Triage de incidentes con IA

**Qué hace:** recibe una alerta, junta lo que pasaba en ese momento y le pide a un modelo de IA un resumen. Ese resumen se valida para que el modelo **no pueda inventar evidencia** ni sugerir acciones fuera de un catálogo cerrado. Solo sugiere: una persona decide.

**4.1 · Ejecutar las pruebas automáticas.** Usan un modelo simulado: no necesitan internet ni clave.
```powershell
.venv\Scripts\python -m pytest reto4-triage-ia\tests -v
```

✔️ **Qué deberías ver:** 13 líneas `PASSED` y al final `13 passed`. Entre ellas están las pruebas que muestran cómo se **detecta una evidencia inventada** (`test_detecta_invencion…`).

**4.2 · Probar el triage sin clave del modelo.** Esto muestra el comportamiento cuando el modelo no está disponible:
```powershell
cd reto4-triage-ia
```
```powershell
..\.venv\Scripts\python -m triage --alerta ..\kit_prueba_portalpagos\alertas\alerta_ejemplo.json
```

✔️ **Qué deberías ver:** un resultado en formato JSON con `"estado": "degradado"`, la acción `RB-00-ESCALAR` y el motivo (`falta TRIAGE_API_KEY`). Aunque no haya modelo, el NOC recibe una respuesta válida.

**4.3 · (Opcional) Probar con el modelo real.** Requiere una cuenta de GitHub:
1. Crea un token en **github.com/settings/personal-access-tokens** → *Generate new token*. En *Account permissions* → **Models**, elige **Read-only**. No agregues otro permiso.
2. En la carpeta `reto4-triage-ia`, copia el archivo `.env.ejemplo` con el nombre `.env`, ábrelo con el Bloc de notas y pega el token después de `TRIAGE_API_KEY=`. Este archivo nunca se sube al repositorio.
3. Ejecuta los 5 casos de prueba:
```powershell
..\.venv\Scripts\python casos\ejecutar_casos.py
```

✔️ **Qué deberías ver:** una tabla con los casos A a E y la lista de errores que detectó el validador. El detalle queda en `reto4-triage-ia\evidencias\`.

Para volver a la carpeta principal:
```powershell
cd ..
```

---

## Reto 5 · Propuesta de 90 días

**Qué hace:** el documento está listo en `reto5-propuesta\propuesta_90_dias.pdf`. Ábrelo con doble clic; no hay que ejecutar nada.

**(Opcional) Regenerar el PDF** después de editar `propuesta_90_dias.md`. Requiere Microsoft Edge, que viene con Windows:
```powershell
.venv\Scripts\python reto5-propuesta\generar_documento.py
```

✔️ **Qué deberías ver:** `PDF: ... (2 paginas)`. Si el documento pasara de 2 páginas, el comando termina con un aviso de error.

---

## Si algo falla

| Mensaje | Qué hacer |
|---|---|
| `python`, `git` o `pwsh` "no se reconoce como comando" | Cierra y vuelve a abrir PowerShell después de instalarlos (paso 0.2) |
| `No such file or directory` o "no se encuentra la ruta" | No estás dentro de la carpeta del proyecto. Ejecuta `cd Prueba_Skandia` |
| `No module named …` | Falta el paso 0.4. Repite la instalación de `requirements.txt` |
| `Invoke-Pester` no se reconoce | Falta instalar Pester (paso 0.2) |
| "la ejecución de scripts está deshabilitada" | Usa los comandos tal como aparecen en esta guía: incluyen `-ExecutionPolicy Bypass`, que solo aplica a esa ejecución |
| El reporte no se abre solo | Ábrelo a mano: `reto1-diagnostico\salidas\reporte.html` |

En Linux o macOS los comandos son los mismos, cambiando `.venv\Scripts\python` por `.venv/bin/python`. El Reto 2 requiere PowerShell 7 (`pwsh`).

---

## Supuestos generales

| # | Supuesto |
|---|---|
| G1 | **No se pudo activar la cuenta gratuita de Azure**. Por eso el Reto 3 no tiene despliegue ni evidencia en Azure. La base de conexión (Azure Function, catálogo de runbooks compartido y consultas KQL) está en el Reto 4 |
| G2 | El kit se incluye **sin modificar**. Toda la limpieza de datos ocurre en el código, nunca a mano |
| G3 | Todas las horas de los informes están en **hora de Colombia (UTC-5)**. Los logs de IIS vienen en UTC y se convierten |
| G4 | Los supuestos de cada reto están en el README de su carpeta |

## Seguridad

- No hay contraseñas, claves ni tokens en el repositorio ni en su historial. Se verificó con `gitleaks` sobre todos los commits.
- Las claves van en un archivo `.env` local, que Git ignora, o en Azure Key Vault.
- El enunciado de la prueba (documento Word) no se incluye en el repositorio.
