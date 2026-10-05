# Propuesta: primeros 90 días en Observabilidad y Automatización

**Para:** Directora de Operaciones de TI · **Caso:** PortalPagos (Andina Financiera) · **Base:** hallazgos de los Retos 1 a 4

**Punto de partida.** El 18/09 el portal falló durante 1 h 44 min en un día de cierre de plazo. Nos enteramos por los clientes, el NOC reportó "100 %" y el caso se cerró sin causa. Los datos muestran que la falla **se podía ver venir 46 horas antes** y que **hoy siguen activos dos riesgos**: el disco C: se llena en días y la caída se repetirá en el próximo día de muchos pagos. Este plan busca tres cosas: **contener esos riesgos, enterarnos antes que el cliente y dejar de depender de reinicios manuales**.

## 1. Iniciativas, en orden de prioridad

| # | Iniciativa | Qué entrega | Impacto | Esfuerzo | Riesgo | Cuándo |
|---|---|---|---|---|---|---|
| 1 | **Contener los riesgos activos** | Liberar disco conservando los volcados de memoria (evidencia). Bajar el log de Debug a Information. Reciclaje del pool por memoria (1 GB) como mitigación temporal. Reemplazar el `.bat` por el script del Reto 2 (sin contraseña, sin `iisreset`) | **Muy alto**: evita la próxima caída | Bajo: días | Bajo: cambios reversibles y probados | Semanas 1-2 |
| 2 | **Monitorear lo que vive el cliente** | Recolección de logs, eventos y métricas en Log Analytics. Una prueba sintética que **inicia sesión y consulta saldos**, en lugar del `/health` actual. Indicador de disponibilidad por operación (SLO 99,9 %). Seis alertas accionables: errores 5xx, latencia p95, pool detenido, memoria del proceso, disco con pronóstico y dumps nuevos. Tableros para la Dirección y el NOC | **Muy alto**: de 0 % a 80 % de incidentes detectados antes que el cliente | Medio | Bajo: solo observa, no cambia el portal | Semanas 2-6 |
| 3 | **Auto-remediación con salvaguardas** | Si el pool se detiene: capturar diagnóstico, iniciarlo y verificar. Máximo 2 intentos por hora. No actúa durante despliegues ni si el problema es de disco. Escala a una persona si falla. Todo queda registrado. Empieza en **modo sugerencia** 2 semanas antes de actuar sola | **Alto**: el tiempo de recuperación baja de 101 min a menos de 15 | Medio | **Medio**: un reinicio automático puede esconder causas; se mitiga con límites, diagnóstico previo y revisión semanal | Semanas 5-9 |
| 4 | **Verificación después de cada despliegue** | Comparación automática de memoria, latencia y errores 24 h antes y después de cada cambio, con el despliegue marcado en el tablero. La salida a producción requiere esa verificación en verde. Post-mortem sin culpables para todo incidente Sev1 | **Alto**: la causa raíz fue un despliegue que nadie vigiló | Medio: es sobre todo acuerdo de proceso | Bajo | Semanas 6-12 |
| 5 | **Triage asistido por IA en el canal del NOC** | Cada alerta llega con un resumen, hipótesis con evidencia citada y un runbook sugerido del catálogo (Reto 4). **Sugiere; la persona decide** | Medio: ahorra los primeros 15-20 min de cada incidente | Bajo: ya está construido | Medio: el modelo puede equivocarse; se mitiga con validación de citas y modo degradado | Semanas 8-12 |

**Por qué en este orden.** La 1 elimina riesgos con fecha. La 2 es la base de todo lo demás: sin datos confiables no se puede automatizar con seguridad. La 3 solo se activa cuando la 2 lleva semanas midiendo bien. La 4 ataca la causa de fondo (cambios sin verificar). La 5 es la de menor impacto: solo aporta si las alertas ya son buenas.

## 2. Cómo mediríamos el éxito

Las líneas base salen de los datos de la semana del 14 al 20 de septiembre.

| Indicador | Hoy (línea base) | Meta a 90 días | Cómo se mide |
|---|---|---|---|
| **Tiempo de detección (MTTD)**: del inicio del impacto a que Operaciones lo reconoce | **79 min** (errores desde las 13:23; ticket crítico a las 14:42) | **< 5 min** | Hora de inicio del impacto en los logs contra la hora de la alerta. Con la alerta de 5xx el incidente se habría detectado a las 13:25 |
| **Tiempo de recuperación (MTTR)**: del inicio del impacto a la recuperación | **101 min** (13:23 a 15:04) | **< 15 min** en fallas del pool | Inicio del impacto contra la vuelta a menos de 1 % de errores |
| **Incidentes detectados antes que el usuario** | **0 %** (0 de 2: la lentitud del 17/09 y la caída del 18/09 llegaron por tickets) | **≥ 80 %** | Hora de la alerta contra hora del primer ticket, revisado en cada post-mortem |
| **Disponibilidad real** (operaciones de clientes sin error) | **98,46 %** en la semana; el NOC reportó 100 % | **≥ 99,9 %** al mes (máximo 43 min de afectación) | Consulta KQL sobre los logs de IIS y HTTP.sys, visible en el tablero de la Dirección |
| **Horas de trabajo manual** (reinicios, revisiones, limpieza y diagnóstico de primer nivel) | **Por medir**: el kit no lo registra. Se medirá las semanas 1 y 2 | **-50 %** | Registro de tiempo del NOC y tickets cerrados por automatización |
| **Despliegues con verificación posterior** | **0 %** | **100 %** | Despliegues con su comparación antes y después en el tablero |
| **Alertas accionables** (que requirieron hacer algo) | Sin alertas de usuario | **≥ 80 %** | Revisión mensual de alertas. Las que no sirven se ajustan o se eliminan |

## 3. Qué necesito que me destrabe

1. **Un cambio de emergencia esta semana** para la iniciativa 1: liberar disco, bajar el log y configurar el reciclaje por memoria. Al ritmo actual, **el disco C: se llena en días**.
2. **Compromiso del equipo de desarrollo** para corregir la caché de sesiones de pago (v2.3.1), y **un dueño del portal** que apruebe el SLO de 99,9 % con el negocio.
3. **Accesos:** permiso para instalar el agente de Azure Monitor en WEB-PAGOS-01; un grupo de recursos con presupuesto para Log Analytics (estimado: decenas de dólares al mes, que se confirmarán con los primeros datos); y una **cuenta gMSA** para el script de mantenimiento (equipo de Directorio Activo).
4. **El calendario de vencimientos de pago**, para revisar capacidad antes de cada día pico.
5. **Una guardia definida y una ruta de escalamiento**: a quién llama la automatización cuando no debe o no puede actuar.
6. **Aval de Seguridad para usar un modelo de IA** con logs: idealmente Azure OpenAI dentro del tenant, revisando antes si las IPs de clientes deben enmascararse.

## 4. Qué no haría, y por qué

| No haría | Por qué |
|---|---|
| Comprar o cambiar de plataforma de monitoreo en estos 90 días | El problema no fue la herramienta sino **qué se medía**. Azure Monitor ya cubre lo necesario; una migración consumiría el trimestre sin reducir el riesgo |
| Automatizar reinicios "a ciegas" o mantener el `iisreset` nocturno | Un reinicio sin límites **oculta la causa**: el `iisreset` diario escondió la fuga hasta el día de más pagos. Solo con diagnóstico previo, límite de intentos y escalamiento |
| Dejar que la IA ejecute acciones | En un portal de pagos regulado, una sugerencia equivocada debe costar un minuto de revisión, no una caída. La IA resume y sugiere; la persona decide |
| Crear decenas de alertas desde el primer día | La fatiga de alertas lleva a ignorarlas. Empezaría con 6 ligadas al impacto en el cliente y agregaría solo las que demuestren ser útiles |
| Tratar las alertas DCOM 10016 como causa (ticket T-10261) | Los datos muestran que aparecen igual toda la semana. Perseguirlas desvía tiempo de los riesgos reales |
| Rediseñar o migrar el portal en este periodo | Es necesario a futuro, pero es un proyecto de otra escala. Primero hay que poder **ver** el sistema para decidir con datos qué cambiar |
