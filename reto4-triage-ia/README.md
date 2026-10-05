# Reto 4 · IA para el triage de incidentes

El componente recibe una alerta de Azure Monitor (esquema común) y el contexto de ese momento, y le pide a un modelo de lenguaje un **resumen en JSON validado**. Ese resumen incluye:
- qué está pasando y su impacto;
- hipótesis con **evidencia citada**;
- una acción sugerida, elegida de un **catálogo cerrado de runbooks**;
- un nivel de confianza.

**El componente no ejecuta nada: sugiere, y una persona decide.**

```
alerta.json ──► contexto (resumido y con ids citables) ──► modelo ──► validación en 3 capas ──► resultado
                 FuenteKit (archivos del kit)                         ├─ válido                 (siempre cumple
                 FuenteLogAnalytics (Reto 3)                          ├─ corregido (2.º intento)  el esquema)
                                                                      └─ degradado → RB-00-ESCALAR
```

| Pieza | Archivo |
|---|---|
| Esquema de salida (JSON Schema 2020-12) | [esquema_triage.json](esquema_triage.json) |
| Catálogo cerrado de runbooks (compartido con el Reto 3) | [catalogo_runbooks.json](catalogo_runbooks.json) |
| Contexto: alerta, eventos, IIS, HTTP.sys, Perfmon y cambios recientes | [triage/contexto.py](triage/contexto.py) |
| Cliente del modelo (API compatible con OpenAI: GitHub Models o Azure OpenAI) | [triage/llm.py](triage/llm.py) |
| Validación: sintaxis, esquema y anti-invención | [triage/validacion.py](triage/validacion.py) |
| Instrucciones al modelo | [triage/prompts.py](triage/prompts.py) |
| Orquestación, corrección y modo degradado | [triage/motor.py](triage/motor.py) |
| Línea de comandos | [triage/\_\_main\_\_.py](triage/__main__.py) |
| Pruebas (13, con modelo simulado) | [tests/test_triage.py](tests/test_triage.py) |
| Casos con el modelo real y evidencia | [casos/](casos/) → [evidencias/](evidencias/) |
| **Base para el Reto 3:** Azure Function que recibe el webhook de la alerta | [azure_function/function_app.py](azure_function/function_app.py) |

## 1. El esquema
| Campo | Contenido |
|---|---|
| `que_esta_pasando` | Resumen para el NOC |
| `impacto` | `nivel` (ninguno, bajo, medio, alto o crítico), descripción y servicios afectados |
| `hipotesis[]` | De 1 a 4. Cada una con `probabilidad` (alta, media o baja) y `evidencia[]`. Cada evidencia es un par `{referencia, cita}`: el id de un elemento del contexto (`EV-L306`, `IIS-1355`…) y un fragmento **copiado literalmente** de ese elemento |
| `accion_sugerida` | `runbook`, que es un `enum` con los 7 ids del catálogo; `justificacion`; y `requiere_aprobacion_humana`, que es `const: true`, así que el modelo no puede desactivarla |
| `confianza` | Número entre 0 y 1 |
| `datos_faltantes[]` | Lo que el modelo necesitaría para estar seguro |

El resultado agrega un bloque `meta`, generado por el código y no por el modelo:
- `estado`: válido, corregido o degradado;
- `intentos` y `errores_detectados`;
- `advertencias`: por ejemplo, cuando se sugiere un runbook de riesgo alto;
- `modelo` y `latencia_ms`;
- un hash del contexto, para que el resultado se pueda auditar.

## 2. Cómo se detecta que el modelo se equivoca o se inventa algo
| Capa | Qué revisa | Qué atrapa |
|---|---|---|
| 1. Sintaxis | Que la respuesta sea JSON (se toleran bloques ```` ```json ````) | Texto libre, respuestas cortadas |
| 2. Esquema | `jsonschema` contra `esquema_triage.json` | Campos faltantes, runbooks fuera del catálogo, `requiere_aprobacion_humana: false`, confianza fuera de rango |
| 3. Anti-invención | Que cada `referencia` **exista** en el contexto y que cada `cita` aparezca **textualmente** en ese elemento | Eventos o líneas inventadas, causas sin respaldo, paráfrasis presentadas como evidencia |

Si falla cualquiera de las tres capas:
1. Se le devuelven al modelo **su respuesta y la lista de errores** para que la corrija, en **un solo intento** adicional.
2. Si vuelve a fallar, se entrega un **resultado degradado**: válido según el esquema, con confianza 0, acción `RB-00-ESCALAR` y el motivo explicado. **La invención nunca llega a la persona.**

Las advertencias no bloquean el resultado; se muestran a quien decide:
- se sugirió un runbook de riesgo alto, como revertir un despliegue;
- la confianza es alta pero el modelo declara datos faltantes;
- la confianza es alta pero ninguna hipótesis tiene probabilidad alta.

## 3. Qué pasa si el modelo falla, se demora o responde algo inválido
| Situación | Comportamiento |
|---|---|
| **Se demora** | El tiempo máximo es de 30 s (`TRIAGE_TIMEOUT_S`). Al vencerse no se reintenta: se entrega el resultado degradado de inmediato, porque una alerta Sev1 no puede esperar al modelo |
| **Error 429 o 5xx del proveedor** | Hasta 2 reintentos, respetando `Retry-After` con un máximo de 10 s. Si siguen fallando, resultado degradado |
| **Error 4xx** (clave inválida, modelo inexistente, contenido filtrado) | No se reintenta: resultado degradado con el motivo |
| **Responde algo inválido o inventado** | Un intento de corrección con la lista de errores. Si vuelve a fallar, resultado degradado |
| **No hay modelo configurado** | Resultado degradado. El NOC recibe igual la alerta resumida y la indicación de escalar |
| **Texto hostil dentro de los logs** (inyección de instrucciones) | El contexto va entre delimitadores y marcado como "dato no confiable". Aunque el modelo obedeciera ese texto, no podría hacer más que sugerir un runbook del catálogo con aprobación humana |

## 4. Casos de prueba
**Con modelo simulado** (`pytest`, sin red ni clave). Son 13 pruebas, entre ellas:
- caso válido;
- **invención detectada y corregida en el segundo intento**: una cita falsa con un id real y un id inexistente (`EV-L9999`);
- invención persistente, que termina en resultado degradado sin que la invención llegue al resultado;
- una paráfrasis presentada como cita;
- JSON inválido y JSON dentro de un bloque Markdown;
- timeout;
- runbook fuera del catálogo (`REINICIAR-SERVIDOR`);
- intento de desactivar la aprobación humana;
- advertencia por acción de riesgo alto;
- texto de inyección dentro de los logs.

**Con el modelo real** (`casos/ejecutar_casos.py`):

| Caso | Alerta | Contexto | Qué se espera |
|---|---|---|---|
| A | La del kit: 5xx > 5 % a las 14:00 | Completo | OutOfMemory en `SesionPagoCache` y relación con la v2.3.1. Diagnóstico antes de reciclar |
| B | Pool detenido a las 14:40 | Completo | Pool deshabilitado tras 5 crashes. Iniciar el pool, sin perder de vista la causa |
| C | **Cebo para invención**: 503 a las 14:45 | **Solo HTTP.sys** | La causa no está en el contexto. Si el modelo "adivina" OutOfMemory sin poder citarlo, el validador lo detecta |
| D | Falsa alarma: warnings DCOM de madrugada | Completo | Impacto bajo, escalar sin actuar |
| E | Invención forzada (modelo simulado) | Completo | Muestra la detección de forma reproducible, aunque el modelo real no se equivoque ese día |

El resultado queda en `evidencias/resumen_casos.md` y en `evidencias/caso_*.json`, que se generan al ejecutar los casos (ver [evidencias/](evidencias/README.md)).

## 5. Cómo reproducirlo
Pruebas, desde la raíz del repositorio:

```bash
.venv/Scripts/python -m pytest reto4-triage-ia/tests -v
```

Modelo real: copia `reto4-triage-ia/.env.ejemplo` como `reto4-triage-ia/.env` y pega un token de GitHub con el permiso **Models: Read**. El archivo `.env` está en `.gitignore`. Después ejecuta los casos:

```bash
cd reto4-triage-ia && ../.venv/Scripts/python casos/ejecutar_casos.py
```

Para una alerta cualquiera:

```bash
cd reto4-triage-ia && ../.venv/Scripts/python -m triage --alerta ../kit_prueba_portalpagos/alertas/alerta_ejemplo.json --salida evidencias/ejemplo.json
```

## 6. Conexión con el Reto 3 (base preparada, pendiente de desplegar)
1. Una **Alert rule** de Azure Monitor dispara un **Action Group** con un webhook al `POST /api/triage` de la Function (`azure_function/`), usando el esquema común.
2. La Function arma el mismo contexto, pero desde **Log Analytics** con `FuenteLogAnalytics`, que consulta las tablas `Event`, `W3CIISLog` y `Perf` con KQL. Se autentica con una **identidad administrada** que tiene el rol *Log Analytics Reader*: no hay credenciales en el código.
3. La clave del modelo es un App Setting que **referencia Key Vault**. Se puede cambiar a Azure OpenAI o AI Foundry sin tocar el código (`TRIAGE_PROVEEDOR=azure`).
4. El resultado queda en Application Insights, para consultarlo desde el tablero del NOC, y se publica en el canal del NOC si está configurado. **La auto-remediación del Reto 3 es independiente:** tiene sus propias salvaguardas y no obedece a esta sugerencia.
5. Los ids del catálogo (`RB-01-INICIAR-POOL`, etc.) son los mismos nombres de los runbooks de Azure Automation del Reto 3.

Pendiente de validar en el Reto 3: las consultas KQL de `FuenteLogAnalytics` contra los nombres reales de las columnas del workspace, y el despliegue de la Function.

## 7. Supuestos y decisiones
| # | Decisión | Por qué |
|---|---|---|
| D1 | **GitHub Models** (`openai/gpt-4.1-mini`) como proveedor por defecto | Es gratis con la cuenta de GitHub y no depende de que la suscripción gratuita de Azure tenga cupo de Azure OpenAI. Expone la misma API, así que pasar a Azure OpenAI es cambiar la configuración |
| D2 | Se envía un contexto **resumido** (bloques de 5 minutos, eventos repetidos agrupados) en lugar de las líneas crudas | Son 1.343 líneas de IIS en 35 minutos. Resumido son 23 elementos (unos 3.000 tokens): cabe en el límite gratuito y deja ids estables que se pueden citar y verificar |
| D3 | Ventana de 30 minutos antes y 5 después de la alerta, más los cambios de los últimos 7 días | Los despliegues son la primera pregunta de un triage. Sin el evento del 15/09, el modelo no podría relacionar la falla con la v2.3.1 |
| D4 | Un solo intento de corrección | Un segundo intento corrige la mayoría de los errores de formato. Más intentos agregan latencia a una alerta crítica |
| D5 | `temperature: 0` | Respuestas más estables y fáciles de comparar entre ejecuciones |
