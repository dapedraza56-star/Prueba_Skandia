#Requires -Version 5.1
<#
.SYNOPSIS
    Demostracion reproducible del mantenimiento sin necesitar el servidor real.

.DESCRIPTION
    Arma en una carpeta temporal un "WEB-PAGOS-01 simulado":
      - logs de IIS (copias de los logs del kit) con fechas de hace 2 a 45 dias,
      - el log del dia en curso (abierto por IIS),
      - 5 volcados de memoria como los del 18/09 y 2 antiguos,
      - temporales viejos y recientes.
    Ejecuta el mantenimiento 3 veces: con -WhatIf, real y otra vez real (idempotencia),
    y guarda el log JSON y un resumen en reto2-powershell/evidencias/.
#>
[CmdletBinding()]
param([string]$Base = (Join-Path ([System.IO.Path]::GetTempPath()) 'demo-mantenimiento'))

$ErrorActionPreference = 'Stop'
$raiz = Resolve-Path (Join-Path $PSScriptRoot '..\..')
$script = Join-Path $PSScriptRoot '..\src\Invoke-MantenimientoPortal.ps1'
$evidencias = Join-Path $PSScriptRoot '..\evidencias'
New-Item -ItemType Directory -Path $evidencias -Force | Out-Null

if (Test-Path $Base) { Remove-Item $Base -Recurse -Force }
$logs = Join-Path $Base 'inetpub\logs\LogFiles\W3SVC2'
$tmp = Join-Path $Base 'PortalPagos\temp'
$dumps = Join-Path $Base 'CrashDumps'
$aud = Join-Path $Base 'fs-auditoria\logs$'
$logJson = Join-Path $Base 'ProgramData\MantenimientoPortal\mantenimiento.jsonl'
New-Item -ItemType Directory -Path $logs, $tmp, $dumps -Force | Out-Null

function Set-Fecha($ruta, $dias) { (Get-Item -LiteralPath $ruta).LastWriteTime = (Get-Date).AddDays(-$dias) }

# Logs: los 8 del kit, envejecidos (los 3 mas viejos superan la retencion de 30 dias)
$kit = Get-ChildItem (Join-Path $raiz 'kit_prueba_portalpagos\logs\iis\W3SVC2') -Filter 'u_ex*.log' |
    Where-Object Name -NotLike '* - copia*' | Sort-Object Name
$edades = 45, 40, 35, 20, 10, 5, 3, 2
for ($i = 0; $i -lt $kit.Count; $i++) {
    $d = Join-Path $logs $kit[$i].Name
    Copy-Item $kit[$i].FullName $d
    Set-Fecha $d $edades[$i]
}
Set-Content (Join-Path $logs ("u_ex{0:yyMMdd}.log" -f (Get-Date))) 'log del dia, abierto por IIS'

# Dumps: 2 antiguos y 5 recientes (como los del 18/09)
foreach ($n in 1, 2) { $f = Join-Path $dumps "w3wp.exe.10$n.dmp"; Set-Content $f ('x' * 1000); Set-Fecha $f (30 + $n) }
foreach ($pid_ in 4471, 7364, 7138, 5703, 3533) { $f = Join-Path $dumps "w3wp.exe.$pid_.dmp"; Set-Content $f ('x' * 1000) }

# Temporales
foreach ($n in 1..3) { $f = Join-Path $tmp "sesion$n.tmp"; Set-Content $f 'tmp'; Set-Fecha $f 3 }
Set-Content (Join-Path $tmp 'en-uso.tmp') 'reciente'

$comunes = @{
    RutaLogsIIS = $logs; RutaAuditoria = $aud; RutaTemporales = $tmp; RutaDumps = $dumps; RutaLog = $logJson
    ServiciosRequeridos = @('Winmgmt'); UmbralDiscoPorcentaje = 5
}
function Get-Inventario {
    [pscustomobject]@{
        logs_iis   = @(Get-ChildItem $logs -File).Count
        auditoria  = @(Get-ChildItem $aud -File -Recurse -ErrorAction SilentlyContinue).Count
        dumps      = @(Get-ChildItem $dumps -File).Count
        temporales = @(Get-ChildItem $tmp -File).Count
    }
}

$inv = Get-Inventario
$filas = @([pscustomobject]@{ Ejecucion = '0. Estado inicial'; Codigo = '-'; logs_iis = $inv.logs_iis
        auditoria = $inv.auditoria; dumps = $inv.dumps; temporales = $inv.temporales })
$motor = (Get-Process -Id $PID).Path
foreach ($e in @(@{ n = '1. Simulacion (-WhatIf)'; w = $true }, @{ n = '2. Ejecucion real'; w = $false }, @{ n = '3. Repeticion (idempotencia)'; w = $false })) {
    $lista = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $script)
    foreach ($k in $comunes.Keys) { $lista += "-$k"; $lista += (@($comunes[$k]) -join ',') }
    if ($e.w) { $lista += '-WhatIf' }
    $null = & $motor @lista 2>&1
    $codigo = $LASTEXITCODE
    $inv = Get-Inventario
    $filas += [pscustomobject]@{ Ejecucion = $e.n; Codigo = $codigo; logs_iis = $inv.logs_iis; auditoria = $inv.auditoria
        dumps = $inv.dumps; temporales = $inv.temporales }
}

$tabla = $filas | Select-Object Ejecucion, Codigo, logs_iis, auditoria, dumps, temporales
$tabla | Format-Table -AutoSize | Out-String | Write-Output
Copy-Item $logJson (Join-Path $evidencias 'demo_mantenimiento.jsonl') -Force
$md = @('# Evidencia de la demostracion del mantenimiento', '',
    "Generado por ``demo/Invoke-Demo.ps1`` con PowerShell $($PSVersionTable.PSVersion) el $(Get-Date -Format 'yyyy-MM-dd HH:mm').", '',
    '| Ejecucion | Codigo de salida | Logs IIS en el servidor | Logs en auditoria | Dumps | Temporales |', '|---|---|---|---|---|---|')
$md += $tabla | ForEach-Object { "| $($_.Ejecucion) | $($_.Codigo) | $($_.logs_iis) | $($_.auditoria) | $($_.dumps) | $($_.temporales) |" }
$md += '', 'Log estructurado completo de las 3 ejecuciones: `demo_mantenimiento.jsonl`.'
Set-Content -Path (Join-Path $evidencias 'demo_resumen.md') -Value $md -Encoding UTF8
Write-Output "Evidencia en: $((Resolve-Path $evidencias).Path)"
