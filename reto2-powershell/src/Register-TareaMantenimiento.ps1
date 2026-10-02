#Requires -Version 5.1
#Requires -RunAsAdministrator
<#
.SYNOPSIS
    Registra (o actualiza) la tarea programada del mantenimiento con una cuenta gMSA.

.DESCRIPTION
    - Con una cuenta de servicio administrada de grupo (gMSA) Windows rota la contraseña solo:
      nadie la conoce y no aparece en ningun script.
    - Idempotente: si la tarea existe, se actualiza con la misma definicion.
    - Usa PowerShell 7 si esta instalado; si no, Windows PowerShell 5.1.

.EXAMPLE
    .\Register-TareaMantenimiento.ps1 -CuentaGmsa 'ANDINA\gmsa-mantweb$' -RutaLogsIIS C:\inetpub\logs\LogFiles\W3SVC2 -RutaAuditoria \\fs-auditoria\logs$ -WhatIf
#>
[CmdletBinding(SupportsShouldProcess)]
param(
    [Parameter(Mandatory)][ValidatePattern('^[^\\]+\\[^\\]+\$$')][string]$CuentaGmsa,
    [Parameter(Mandatory)][string]$RutaLogsIIS,
    [Parameter(Mandatory)][string]$RutaAuditoria,
    [string]$NombreTarea = 'MantenimientoDiarioPortal',
    [string]$CarpetaTarea = '\Mantenimiento\',
    [datetime]$Hora = '02:00',
    [string]$RutaScript = (Join-Path $PSScriptRoot 'Invoke-MantenimientoPortal.ps1')
)

$motor = (Get-Command pwsh.exe -ErrorAction SilentlyContinue).Source
if (-not $motor) { $motor = (Get-Command powershell.exe).Source }

$argumentos = "-NoProfile -NonInteractive -ExecutionPolicy RemoteSigned -File `"$RutaScript`" " +
              "-RutaLogsIIS `"$RutaLogsIIS`" -RutaAuditoria `"$RutaAuditoria`""
$accion = New-ScheduledTaskAction -Execute $motor -Argument $argumentos
$disparador = New-ScheduledTaskTrigger -Daily -At $Hora
$principal = New-ScheduledTaskPrincipal -UserId $CuentaGmsa -LogonType Password -RunLevel Highest
$config = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Hours 1) -MultipleInstances IgnoreNew `
    -StartWhenAvailable

if ($PSCmdlet.ShouldProcess("$CarpetaTarea$NombreTarea", "Registrar tarea como $CuentaGmsa a las $($Hora.ToString('HH:mm'))")) {
    Register-ScheduledTask -TaskName $NombreTarea -TaskPath $CarpetaTarea -Action $accion -Trigger $disparador `
        -Principal $principal -Settings $config -Force | Out-Null
    Write-Output "Tarea $CarpetaTarea$NombreTarea registrada. Deshabilite la tarea anterior \Mantenimiento\MantenimientoDiarioIIS."
}
