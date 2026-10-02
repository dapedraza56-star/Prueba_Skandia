# Kit de datos: caso "PortalPagos", Andina Financiera (empresa ficticia)

Todos los datos de este kit son **sintéticos**. No corresponden a ninguna empresa, cliente ni persona real.

Servidor: `WEB-PAGOS-01`, Windows Server 2022, IIS 10, zona horaria (UTC-05:00) Bogotá.
Sitio IIS: `PortalPagos` (ID 2), pool de aplicaciones: `PortalPagosPool`.
Periodo: semana del lunes 14 al domingo 20 de septiembre de 2026.

| Carpeta | Contenido | Origen |
|---|---|---|
| `logs/iis/W3SVC2/` | Logs W3C del sitio | Copiados tal cual del servidor por el equipo de soporte |
| `logs/httperr/` | Log de HTTP.sys | Idem |
| `eventos/` | Visor de eventos (System, Application, TaskScheduler) | `Get-WinEvent ... \| Export-Csv` ejecutado en el servidor |
| `metricas/` | Contadores de rendimiento cada 5 minutos | Recopilador de datos de Perfmon, exportado a CSV |
| `tickets/` | Tickets de la mesa de servicio de la semana | Exportación de la herramienta de mesa de servicio |
| `scripts/` | Script de mantenimiento diario y su log | Copiado de `C:\scripts\` |
| `alertas/` | Ejemplo de alerta en el esquema común de Azure Monitor | Para el Reto 4 |

Los archivos se entregan como los dejó el equipo de soporte, sin depurar.
