# Evidencia de la demostracion del mantenimiento

Generado por `demo/Invoke-Demo.ps1` con PowerShell 5.1.19041.6456 el 2026-10-02 14:14.

| Ejecucion | Codigo de salida | Logs IIS en el servidor | Logs en auditoria | Dumps | Temporales |
|---|---|---|---|---|---|
| 0. Estado inicial | - | 9 | 0 | 7 | 4 |
| 1. Simulacion (-WhatIf) | 0 | 9 | 0 | 7 | 4 |
| 2. Ejecucion real | 0 | 6 | 8 | 5 | 1 |
| 3. Repeticion (idempotencia) | 0 | 6 | 8 | 5 | 1 |

Log estructurado completo de las 3 ejecuciones: `demo_mantenimiento.jsonl`.
