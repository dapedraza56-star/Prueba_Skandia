#Requires -Version 5.1
<#
.SYNOPSIS
    Mantenimiento diario de PortalPagos. Reemplaza a mantenimiento_diario.bat (2019).

.DESCRIPTION
    Orden de los pasos (cada uno registra su resultado en un log JSON):
      1. Precondiciones: valida rutas; si algo no existe, termina con codigo 2 sin tocar nada.
      2. Espacio en disco: advierte si queda menos del umbral.
      3. Copia verificada (SHA-256) de los logs de IIS a auditoria.
      4. Borra logs con mas de -DiasRetencionLogs dias, SOLO si su copia esta verificada.
      5. Borra temporales viejos de la carpeta temporal de la aplicacion.
      6. Retencion de volcados de memoria: conserva siempre los mas recientes y avisa si hay nuevos.
      7. Verifica el pool de IIS y su memoria (solo informa, no reinicia).
      8. Asegura que los servicios indicados esten en ejecucion (solo inicia si estan detenidos).

    Lo que ya NO hace, y por que (ver README):
      - iisreset diario: cortaba el servicio y ocultaba la fuga de memoria del 18/09.
      - Reiniciar "Servicio Notificaciones" a ciegas: se reemplaza por iniciar solo si esta detenido.
      - Borrar todos los dumps: son la evidencia para encontrar la causa de una caida.
      - net use con contraseña en texto plano: el acceso lo da la identidad de la tarea (gMSA).

.PARAMETER RutaLogsIIS
    Carpeta de logs del sitio. Debe existir (el 16/09 se retiro D: y el .BAT siguio "OK").

.PARAMETER RutaAuditoria
    Carpeta o recurso UNC de auditoria. Se crea la subcarpeta del servidor.

.PARAMETER Credencial
    Opcional. Identidad alternativa para el recurso de auditoria. Nunca se guarda en el script:
    obtenerla con Get-Secret (SecretManagement) o Get-StoredCredential en quien lo invoca.

.EXAMPLE
    .\Invoke-MantenimientoPortal.ps1 -RutaLogsIIS C:\inetpub\logs\LogFiles\W3SVC2 -RutaAuditoria \\fs-auditoria\logs$ -WhatIf

.NOTES
    Codigos de salida: 0 OK (puede haber advertencias en el log), 1 algun paso fallo,
    2 parametros/precondiciones invalidos, 3 otra ejecucion en curso, 4 error inesperado.
#>
[CmdletBinding(SupportsShouldProcess)]
param(
    [Parameter(Mandatory)]
    [ValidateNotNullOrEmpty()]
    [string]$RutaLogsIIS,

    [Parameter(Mandatory)]
    [ValidateNotNullOrEmpty()]
    [string]$RutaAuditoria,

    [ValidateRange(1, 365)]
    [int]$DiasRetencionLogs = 30,

    [string]$RutaTemporales,

    [ValidateRange(1, 720)]
    [int]$HorasRetencionTemporales = 24,

    [string]$RutaDumps = 'C:\CrashDumps',

    [ValidateRange(1, 365)]
    [int]$DiasRetencionDumps = 14,

    [ValidateRange(1, 50)]
    [int]$DumpsAConservar = 3,

    [string]$PoolIIS = 'PortalPagosPool',

    [ValidateRange(100, 64000)]
    [int]$UmbralMemoriaPoolMB = 1000,

    [string[]]$ServiciosRequeridos = @('Servicio Notificaciones'),

    [ValidateRange(1, 90)]
    [int]$UmbralDiscoPorcentaje = 15,

    [string]$RutaLog = (Join-Path $env:ProgramData 'MantenimientoPortal\mantenimiento.jsonl'),

    [pscredential]$Credencial
)

$ErrorActionPreference = 'Stop'
Import-Module (Join-Path $PSScriptRoot 'MantenimientoPortal.psm1') -Force
$wi = @{ WhatIf = [bool]$WhatIfPreference }   # los modulos no heredan -WhatIf: se pasa explicito

Initialize-LogMantenimiento -Ruta $RutaLog -Simulacion:([bool]$WhatIfPreference)
$mutex = $null
$codigo = 4
try {
    # Una sola ejecucion a la vez (p.ej. si alguien la lanza a mano mientras corre la tarea)
    $mutex = New-Object System.Threading.Mutex($false, 'Global\MantenimientoPortalPagos')
    if (-not $mutex.WaitOne(0)) {
        Write-LogMantenimiento -Nivel ERROR -Paso 'inicio' -Mensaje 'Ya hay otra ejecucion en curso'
        $mutex = $null
        $codigo = 3
        return
    }

    $parametros = @{}
    foreach ($k in $PSBoundParameters.Keys) { if ($k -ne 'Credencial') { $parametros[$k] = "$($PSBoundParameters[$k])" } }
    Write-LogMantenimiento -Nivel INFO -Paso 'inicio' -Mensaje 'Inicio del mantenimiento' -Datos @{ parametros = $parametros; ps = "$($PSVersionTable.PSVersion)" }

    # 1. Precondiciones: si algo falta, no se toca nada
    $faltantes = @(@($RutaLogsIIS) + @($RutaTemporales | Where-Object { $_ }) | Where-Object { -not (Test-Path -LiteralPath $_ -PathType Container) })
    if ($faltantes.Count -gt 0) {
        Write-LogMantenimiento -Nivel ERROR -Paso 'precondiciones' -Mensaje "No existen: $($faltantes -join ', ')" -Datos @{ faltantes = $faltantes }
        $codigo = 2
        return
    }

    $resultados = New-Object System.Collections.Generic.List[object]
    $resultados.Add((Get-EstadoDisco -Ruta $RutaLogsIIS -UmbralPorcentaje $UmbralDiscoPorcentaje))

    $argsCopia = @{ Origen = $RutaLogsIIS; Destino = (Join-Path $RutaAuditoria $env:COMPUTERNAME) }
    if ($Credencial) { $argsCopia.Credencial = $Credencial }
    $copia = Copy-LogsAuditoria @argsCopia @wi
    $resultados.Add($copia)

    # Solo se borran los logs cuya copia en auditoria se verifico
    $resultados.Add((Remove-ArchivoAntiguo -Paso 'logs_iis' -Ruta $RutaLogsIIS -Filtro '*.log' -Dias $DiasRetencionLogs `
                -SoloSiEstanEn $copia.Verificados -Recursivo @wi))

    if ($RutaTemporales) {
        $resultados.Add((Remove-ArchivoAntiguo -Paso 'temporales' -Ruta $RutaTemporales -Filtro '*.tmp' `
                    -Dias ($HorasRetencionTemporales / 24) @wi))
    }

    $resultados.Add((Get-DumpReciente -Ruta $RutaDumps))
    $resultados.Add((Remove-ArchivoAntiguo -Paso 'dumps' -Ruta $RutaDumps -Filtro '*.dmp' -Dias $DiasRetencionDumps `
                -ConservarUltimos $DumpsAConservar @wi))

    $resultados.Add((Get-EstadoPoolIIS -Pool $PoolIIS -UmbralMemoriaMB $UmbralMemoriaPoolMB))
    foreach ($s in $ServiciosRequeridos) { $resultados.Add((Assert-ServicioEnEjecucion -Nombre $s @wi)) }

    $codigo = Get-CodigoSalida -Resultados $resultados
    $resumen = @{}
    foreach ($r in $resultados) { $resumen[$r.Paso] = $r.Estado }
    $nivelFin = if ($codigo -eq 0) { 'INFO' } else { 'ERROR' }
    Write-LogMantenimiento -Nivel $nivelFin -Paso 'fin' -Mensaje "Fin del mantenimiento (codigo $codigo)" -Datos @{ codigo = $codigo; pasos = $resumen }
    $resultados | Select-Object Paso, Estado, Mensaje
} catch {
    Write-LogMantenimiento -Nivel ERROR -Paso 'inesperado' -Mensaje $_.Exception.Message -Datos @{ linea = $_.InvocationInfo.ScriptLineNumber }
    $codigo = 4
} finally {
    if ($mutex) { $mutex.ReleaseMutex(); $mutex.Dispose() }
    # exit solo cuando corre como script (tarea programada); no cierra la consola si se usa con punto
    if ($MyInvocation.InvocationName -ne '.') { exit $codigo }
}
