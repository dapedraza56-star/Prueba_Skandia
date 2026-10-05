# Bitácora de uso de IA

## 1. Herramientas y modelos

| Herramienta | Modelo | Para qué |
|---|---|---|
| Claude Code | Claude Opus 5.5 | Leer el enunciado, preparar el entorno, explorar los datos, escribir el código de análisis y las pruebas, y redactar borradores del post-mortem |
| VS Code + extensión de Python y panel de pruebas | — | Ejecutar y validar yo mismo el código y las pruebas que generó la IA |
 |

## 2. Prompts clave

| # | Prompt (resumen) | Qué respondió la IA | Qué hice con eso |
|---|---|---|---|
| 1 | "Interpreta el Word del reto y enlista temas, herramientas y entornos" | Extrajo el texto del .docx y lo resumió por reto. Al revisar el kit por encima, advirtió las trampas: logs en UTC, archivo duplicado, `/health` engañoso, contraseña en el .BAT | Usé el resumen para planear los 5 retos y decidir el orden: primero el Reto 1, porque todo lo demás depende del diagnóstico. Comparé el resumen con el Word original para confirmar que no faltara ningún entregable.  |
| 2 | "¿Qué entornos debo habilitar para Azure y el resto de la prueba?" | Revisó qué había instalado en el equipo y propuso una lista de instalación. Separó lo que debía hacer yo (cuentas, tarjeta, presupuesto) de lo que podía instalar ella | Acepté la lista, pero separé lo que me tocaba a mí: crear la cuenta de Azure y el inicio de sesión en GitHub. No le pasé ninguna contraseña. Elegí yo la extensión de KQL (Kuskus). |
| 3 | "Instalacion de las herramientas" | Se Instaló PowerShell 7, Azure CLI, Bicep, gh, gitleaks, Pester, módulos Az y el entorno Python | Validé versiones. No le di credenciales: el login de GitHub y el de Azure los hice yo |
| 4 | "Iniciemos con la parte 1" | Exploró cada fuente, construyó `carga.py` y `analisis.py`, y propuso la causa raíz con evidencia | Ejecuté las pruebas en VS Code (4 de 4 en verde) y `analisis.py`. Abrí en el kit las líneas citadas — eventos 109, 304 y 366, y la línea 5 de httperr1.log. Hice fallar una prueba a propósito para comprobar que detecta errores|
| 5 | "Mejora analisis.py para no ver resultados en la terminal; algo más visual" | Generó un reporte HTML autocontenido (sin CDN) con indicadores, tablas ordenables y filtrables, gráficas incrustadas y modo oscuro. La misma estructura alimenta el Markdown, para que las dos versiones no se contradigan | La idea del reporte visual fue mía: la salida en la terminal no servía para presentar resultados. Revisé el reporte ppara validar la información consolidada. |
| 6 | "Simplifica el reporte a lo que pide la prueba, con los colores corporativos de Skandia" | Leyó la paleta del CSS público de skandia.co (verde #00C83C, grises #3F3F3F/#362E2E, error #E12B1C, Montserrat). Reorganizó el reporte en las 5 preguntas del Reto 1 y pasó la calidad de datos y los eventos a anexos plegables. En la primera versión el modo oscuro usaba el gris burdeos de la marca y se veía marrón; se cambió a grises neutros | Pedí simplificar porque la primera versión del reporte tenía más información de la que pide la prueba. Le indiqué que se ciñera a las 5 preguntas del Reto 1 y usara los colores de Skandia. Decidí no incluir el logo de Skandia porque el caso es de una empresa ficticia |
| 7 | "Iniciemos la etapa 2" | Listó 12 problemas del .BAT por riesgo, cruzados con la evidencia del Reto 1. Escribió el módulo, el script, el registro de la tarea con gMSA, 31 pruebas Pester y una demo reproducible | Revisé la tabla de riesgos del `.bat`. Ejecuté las pruebas Pester [en PowerShell 5.1 y 7] |
| 8 | "Iniciemos el reto 4 dejando las bases de conexión para el 3" | Diseñó el esquema con citas verificables, el catálogo cerrado compartido con el Reto 3, la validación en 3 capas con corrección y modo degradado, 13 pruebas con modelo simulado, 5 casos para el modelo real y una Azure Function base que recibe el webhook y consulta Log Analytics | Decidí usar GitHub Models en lugar de Azure OpenAI para no depender de la suscripción. El token lo creé yo con el permiso mínimo (*Models: Read*) y lo guardé en `.env`, nunca en el chat. ` |
| 9 | "Iniciemos con la prueba número 5" | Calculó las líneas base de MTTD, MTTR y disponibilidad con los datos del Reto 1.Se Redactó 5 iniciativas priorizadas por impacto, esfuerzo y riesgo,validando en conjunto los items de proyeccion de la propuesta teniendo en cuenta el analisis de categorización de las prioridades segun las los incidentes que detecte y asi se generó el PDF verificando el límite de 2 páginas.   |


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
| E11 | En el contexto del triage, el texto del evento OutOfMemory se cortaba en 260 caracteres, **justo antes de la pila `SesionPagoCache.Agregar`**, que es la evidencia clave. El modelo no habría podido citarla | Leer el contexto generado antes de enviarlo al modelo | Límite de 420 caracteres para eventos y una prueba que exige que la pila esté en el contexto |
| E12 | **Detectado por mí.** La primera versión del reporte del Reto 1 tenía 7 secciones y 6 indicadores, con información que la prueba no pide (por ejemplo, tablas técnicas de calidad de datos al mismo nivel que las conclusiones). Para la Directora era difícil de leer | Al abrir el reporte en el navegador y compararlo con lo que pide el enunciado | Pedí reorganizarlo en las 5 preguntas del reto. El detalle técnico pasó a anexos plegables |


## 4. Cómo validé lo que generó la IA y qué no le delegué

**Validación:**
- Pruebas automáticas de las decisiones de limpieza que cambian las conclusiones: zona horaria, duplicado, esquema y ventana de la caída (`reto1-diagnostico/tests`).
- Cada cifra del post-mortem sale de `analisis.py` y se puede regenerar.
- Se cruzan fuentes independientes. Por ejemplo, la caída según HTTP.sys (14:38–15:04) coincide con el ticket T-10255, y el modelo de memoria predice el OutOfMemory con 2.369 confirmaciones cuando el observado fue 2.387.
- Ejecuté yo mismo, en VS Code, las pruebas del Reto 1 (4/4) , las del Reto 2 (31/31) y las del Reto 4 (13/13).
- Abrí los archivos del kit en las líneas citadas y comprobé que dicen lo que afirma el informe: despliegue en la línea 109, primer OutOfMemory en la 304, pool deshabilitado en la 366.
- Hice fallar una prueba a propósito para confirmar que no pasan siempre.
- Ejecuté la demo del Reto 2 y verifiqué que la simulación con -WhatIf no tocó ningún archivo.

**Lo que no delegué:**
- Credenciales: los logins de GitHub y Azure y el token del modelo los hago yo, y nunca entran al chat ni al repositorio.
- **Hecho contra hipótesis:** revisé la tabla del post-mortem. Por ejemplo, dejé como hipótesis (P2) que el pool corre en 32 bits, porque los datos muestran el síntoma (OutOfMemory con 4,7 GB libres) pero no la configuración. Afirmarlo sin ver `applicationHost.config` sería inventar. `.
- **Qué no le pedí a la IA:** Creacion de repositorios para la trazabilidad del proyecto, confirmacion de las pruebas segun cada item a evaluar, validando la información.
