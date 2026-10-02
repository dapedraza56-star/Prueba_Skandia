# Bitácora de uso de IA

> Se lleva durante el trabajo, no al final. Las entradas marcadas con ✍️ debe completarlas o revisarlas el autor con su propio criterio.

## 1. Herramientas y modelos

| Herramienta | Modelo | Para qué |
|---|---|---|
| Claude Code (app de escritorio) | Claude Opus 5.5 | Leer el enunciado, preparar el entorno, explorar los datos, escribir el código de análisis y las pruebas, y redactar borradores del post-mortem |
| ✍️ (otras que uses: ChatGPT, Copilot…) | | |

## 2. Prompts clave

| # | Prompt (resumen) | Qué respondió la IA | Qué hice con eso |
|---|---|---|---|
| 1 | "Interpreta el Word del reto y enlista temas, herramientas y entornos" | Extrajo el texto del .docx y lo resumió por reto. Al revisar el kit por encima, advirtió las trampas: logs en UTC, archivo duplicado, `/health` engañoso, contraseña en el .BAT | ✍️ |
| 2 | "¿Qué entornos debo habilitar para Azure y el resto de la prueba?" | Revisó qué había instalado en el equipo y propuso una lista. Separó lo que debía hacer yo (cuentas, tarjeta, presupuesto) de lo que podía instalar ella | ✍️ |
| 3 | "Instala lo que puedas" | Instaló PowerShell 7, Azure CLI, Bicep, gh, gitleaks, Pester, módulos Az y el entorno Python | Validé versiones. No le di credenciales: el login de GitHub y el de Azure los hice yo |
| 4 | "Iniciemos con la parte 1" | Exploró cada fuente, construyó `carga.py` y `analisis.py`, y propuso la causa raíz con evidencia | ✍️ (qué revisaste tú, qué cifras verificaste a mano) |
| 5 | "Mejora analisis.py para no ver resultados en la terminal; algo más visual" | Generó un reporte HTML autocontenido (sin CDN) con indicadores, tablas ordenables y filtrables, gráficas incrustadas y modo oscuro. La misma estructura alimenta el Markdown, para que las dos versiones no se contradigan | ✍️ |
| 6 | "Simplifica el reporte a lo que pide la prueba, con los colores corporativos de Skandia" | Leyó la paleta del CSS público de skandia.co (verde #00C83C, grises #3F3F3F/#362E2E, error #E12B1C, Montserrat). Reorganizó el reporte en las 5 preguntas del Reto 1 y pasó la calidad de datos y los eventos a anexos plegables. En la primera versión el modo oscuro usaba el gris burdeos de la marca y se veía marrón; se cambió a grises neutros | ✍️ |
| 7 | "Iniciemos la etapa 2" | Listó 12 problemas del .BAT por riesgo, cruzados con la evidencia del Reto 1. Escribió el módulo, el script, el registro de la tarea con gMSA, 31 pruebas Pester y una demo reproducible | ✍️ (revisa la tabla de riesgos: ¿estás de acuerdo con el orden?) |
| 8 | ✍️ | | |

## 3. Situaciones en las que la IA se equivocó o propuso algo riesgoso

| # | Qué pasó | Cómo se detectó | Corrección |
|---|---|---|---|
| E1 | El primer modelo de fuga de memoria usó **todas las peticiones** como variable. Daba R² 0,94, pero el viernes tenía una pendiente distinta, y eso habría llevado a un pronóstico equivocado | En la gráfica de dispersión, el 18/09 se separaba de los demás días. Se probaron 3 predictores alternativos | Usar `/api/pagos/confirmar`: R² 0,999 y pendiente estable. Además coincide con la pila del error (`SesionPagoCache.Agregar`) |
| E2 | La regla de "ventana no disponible" (más de 5 % de errores) contaba como caída **1 error aislado de madrugada** sobre 10 peticiones, y mostraba días normales con 5–10 minutos de caída | Los resultados eran inverosímiles para días sin tickets | Se exige además un mínimo de 3 fallas por ventana. Queda documentado en el código |
| E3 | El primer pronóstico de disco tenía escenarios "optimista" y "pesimista" basados en el intervalo de confianza del coeficiente, y daban **la misma fecha**. Con datos sintéticos el ajuste es casi perfecto, así que ese intervalo no representa la incertidumbre real | Las tres filas de la tabla eran idénticas | Se cambió a escenarios de **tráfico** (bajo, normal y alto), que es donde está la incertidumbre de verdad |
| E4 | La línea citada del cambio de esquema W3C era incorrecta (2352 en vez de 2351), porque se tomaba la "primera fila" después de ordenar por hora | Se verificó el archivo directamente con `sed -n '2350,2353p'` | Se ordena por hora y número de línea y se cita la directiva `#Fields` |
| E5 | `winget` falló al instalar PowerShell 7 en formato MSIX (error de red `0x80072ee2`) | La salida del comando | Se instaló el MSI con `--installer-type wix` |
| E6 | Al calcular la memoria del pool, `Measure-Object -Sum` sobre una lista vacía **lanza un error en modo estricto**. Pasa justo cuando el pool está detenido, que es el escenario del 18/09 a las 14:38: el script habría fallado cuando más se le necesitaba | Una prueba Pester del pool detenido, sin procesos w3wp | La suma se hace a mano y la prueba quedó como regresión |
| E7 | Se usó `Get-FileHash` para verificar las copias. En **Windows PowerShell 5.1 no devuelve nada cuando `-WhatIf` está activo** (en 7 sí), así que la simulación terminaba con código 1 solo en 5.1 | Correr las mismas pruebas en las dos versiones | Hash calculado con .NET (`SHA256`), con el mismo comportamiento en 5.1 y 7 |
| E8 | El log JSON se escribía con `Add-Content -Encoding UTF8`, que en 5.1 **antepone un BOM** y vuelve inválida la primera línea JSON al ingerirla | Revisar los primeros bytes del archivo de evidencia | Escritura con `UTF8Encoding($false)` y una prueba que verifica que no haya BOM |
| E9 | Los archivos se guardaron sin BOM. En 5.1, las tildes y la "ñ" de los mensajes se leen mal. También había nombres en plural, contra la convención de PowerShell | PSScriptAnalyzer, ejecutado como prueba | Archivos .ps1/.psm1 en UTF-8 con BOM y funciones renombradas (`Remove-ArchivoAntiguo`, `Get-DumpReciente`) |
| E10 | La primera prueba de "no usa `net use`" buscaba el texto y fallaba porque aparecía en la documentación | La prueba falló con el script correcto | La prueba analiza el árbol sintáctico (AST) y revisa comandos reales, no comentarios |
| ✍️ | (agrega los que encuentres al revisar) | | |

## 4. Cómo validé lo que generó la IA y qué no le delegué

**Validación:**
- Pruebas automáticas de las decisiones de limpieza que cambian las conclusiones: zona horaria, duplicado, esquema y ventana de la caída (`reto1-diagnostico/tests`).
- Cada cifra del post-mortem sale de `analisis.py` y se puede regenerar.
- Se cruzan fuentes independientes. Por ejemplo, la caída según HTTP.sys (14:38–15:04) coincide con el ticket T-10255, y el modelo de memoria predice el OutOfMemory con 2.369 confirmaciones cuando el observado fue 2.387.
- ✍️ Revisión manual: abrí los archivos en las líneas citadas y comprobé que dicen lo que el informe afirma.

**Lo que no delegué:**
- Credenciales: los logins de GitHub y Azure y el token del modelo los hago yo, y nunca entran al chat ni al repositorio.
- La decisión de qué es hecho y qué es hipótesis en el post-mortem: ✍️.
- ✍️
