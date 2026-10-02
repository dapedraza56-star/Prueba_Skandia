<#
.SYNOPSIS
    Prepara la carpeta azure_function para publicarla: copia el paquete triage/ y los contratos JSON.
.EXAMPLE
    ./scripts/empaquetar.ps1; func azure functionapp publish <nombre-function-app>
#>
[CmdletBinding(SupportsShouldProcess)]
param()
$base = Split-Path $PSScriptRoot -Parent
$destino = Join-Path $base 'azure_function'
foreach ($item in 'triage', 'esquema_triage.json', 'catalogo_runbooks.json') {
    if ($PSCmdlet.ShouldProcess($item, "Copiar a $destino")) {
        Copy-Item (Join-Path $base $item) $destino -Recurse -Force
    }
}
