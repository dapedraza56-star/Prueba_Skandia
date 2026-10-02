#Requires -Version 5.1
<#
.SYNOPSIS
    Funciones del mantenimiento diario de PortalPagos (reemplazo de mantenimiento_diario.bat).

.DESCRIPTION
    Cada paso es una funcion independiente, probada con Pester, que:
      - respeta -WhatIf / -Confirm (SupportsShouldProcess),
      - devuelve un objeto con el resultado (no escribe en pantalla),
      - registra lo que hace en un log estructurado (JSON por linea),
      - se puede ejecutar varias veces sin efectos no deseados (idempotente).
    Compatible con Windows PowerShell 5.1 y PowerShell 7.
#>

Set-StrictMode -Version Latest

$script:ArchivoLog = $null
$script:IdEjecucion = $null
$script:Simulacion = $false

# ----------------------------------------------------------------------------- log
function Initialize-LogMantenimiento {
    <# Define el archivo de log (JSON Lines) y el identificador de esta ejecucion. #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$Ruta,
        [string]$IdEjecucion = ([guid]::NewGuid().ToString()),
        [switch]$Simulacion
    )
    $script:Simulacion = [bool]$Simulacion
    $carpeta = Split-Path -Path $Ruta -Parent
    if ($carpeta -and -not (Test-Path -LiteralPath $carpeta)) {
        New-Item -ItemType Directory -Path $carpeta -Force -WhatIf:$false | Out-Null
    }
    $script:ArchivoLog = $Ruta
    $script:IdEjecucion = $IdEjecucion
}

function Write-LogMantenimiento {
    <# Escribe una linea JSON: ts, nivel, paso, mensaje, datos. Nunca falla el mantenimiento por el log. #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][ValidateSet('INFO', 'ADVERTENCIA', 'ERROR')][string]$Nivel,
        [Parameter(Mandatory)][string]$Paso,
        [Parameter(Mandatory)][string]$Mensaje,
        [hashtable]$Datos = @{}
    )
    $registro = [ordered]@{
        ts        = (Get-Date).ToString('o')
        nivel     = $Nivel
        paso      = $Paso
        mensaje   = $Mensaje
        equipo    = $env:COMPUTERNAME
        ejecucion = $script:IdEjecucion
        simulacion = ($script:Simulacion -or [bool]$WhatIfPreference)
        datos     = $Datos
    }
    $linea = $registro | ConvertTo-Json -Compress -Depth 5
    Write-Verbose $linea
    if ($script:ArchivoLog) {
        try {
            # UTF-8 sin BOM: en 5.1 Add-Content -Encoding UTF8 pone BOM y rompe la primera linea JSON
            # al ingerir el archivo (Azure Monitor, Python, jq)
            [System.IO.File]::AppendAllText($script:ArchivoLog, $linea + [Environment]::NewLine,
                (New-Object System.Text.UTF8Encoding($false)))
        } catch {
            Write-Warning "No se pudo escribir el log: $($_.Exception.Message)"
        }
    }
}

function New-ResultadoPaso {
    # Solo construye un objeto en memoria; no cambia el estado del sistema
    [Diagnostics.CodeAnalysis.SuppressMessageAttribute('PSUseShouldProcessForStateChangingFunctions', '')]
    param([string]$Paso, [string]$Estado = 'OK', [hashtable]$Datos = @{}, [string]$Mensaje = '')
    [pscustomobject]@{ Paso = $Paso; Estado = $Estado; Mensaje = $Mensaje; Datos = $Datos }
}

# ---------------------------------------------------------------------- disco
function Get-EstadoDisco {
    <# Espacio libre de la unidad que contiene la ruta. Advierte por debajo del umbral. #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$Ruta,
        [ValidateRange(1, 90)][int]$UmbralPorcentaje = 15
    )
    $raiz = [System.IO.Path]::GetPathRoot((Resolve-Path -LiteralPath $Ruta).ProviderPath)
    $info = New-Object System.IO.DriveInfo($raiz)
    $pct = [math]::Round(100 * $info.AvailableFreeSpace / $info.TotalSize, 1)
    $datos = @{ unidad = $raiz; libre_gb = [math]::Round($info.AvailableFreeSpace / 1GB, 2); libre_pct = $pct }
    if ($pct -lt $UmbralPorcentaje) {
        Write-LogMantenimiento -Nivel ADVERTENCIA -Paso 'disco' -Mensaje "Espacio libre $pct % < umbral $UmbralPorcentaje %" -Datos $datos
        return New-ResultadoPaso -Paso 'disco' -Estado 'ADVERTENCIA' -Datos $datos -Mensaje "Libre $pct %"
    }
    Write-LogMantenimiento -Nivel INFO -Paso 'disco' -Mensaje "Espacio libre $pct %" -Datos $datos
    New-ResultadoPaso -Paso 'disco' -Datos $datos -Mensaje "Libre $pct %"
}

# ------------------------------------------------------------------ auditoria
function Get-HashSha256 {
    <#
    SHA-256 de un archivo con .NET. No se usa Get-FileHash porque en Windows PowerShell 5.1
    no devuelve nada cuando -WhatIf esta activo (en PowerShell 7 si), y eso rompia la simulacion.
    #>
    param([Parameter(Mandatory)][string]$Ruta)
    $sha = [System.Security.Cryptography.SHA256]::Create()
    $fs = [System.IO.File]::Open($Ruta, 'Open', 'Read', 'ReadWrite')
    try { [System.BitConverter]::ToString($sha.ComputeHash($fs)).Replace('-', '') }
    finally { $fs.Dispose(); $sha.Dispose() }
}

function Copy-LogsAuditoria {
    <#
    .SYNOPSIS
        Copia a la carpeta de auditoria los .log que aun no esten alli (o que cambiaron),
        y verifica cada copia con SHA-256. Devuelve las rutas de origen verificadas.
    .NOTES
        No mapea unidades ni usa contraseñas: el acceso al recurso compartido lo da la
        identidad de la tarea programada (cuenta gMSA). Si se requiere otra identidad,
        el llamador pasa -Credencial (por ejemplo desde SecretManagement).
        Se omite el log del dia en curso porque IIS lo mantiene abierto.
    #>
    [CmdletBinding(SupportsShouldProcess)]
    param(
        [Parameter(Mandatory)][string]$Origen,
        [Parameter(Mandatory)][string]$Destino,
        [pscredential]$Credencial
    )
    $paso = 'auditoria'
    $unidad = $null
    try {
        if ($Credencial) {
            $unidad = New-PSDrive -Name ("Aud" + [guid]::NewGuid().ToString('N').Substring(0, 6)) -PSProvider FileSystem `
                -Root $Destino -Credential $Credencial -ErrorAction Stop -WhatIf:$false
            $Destino = $unidad.Root
        }
        if (-not (Test-Path -LiteralPath $Destino)) {
            if ($PSCmdlet.ShouldProcess($Destino, 'Crear carpeta de auditoria')) {
                New-Item -ItemType Directory -Path $Destino -Force -ErrorAction Stop | Out-Null
            }
        }
        $hoy = (Get-Date).Date
        $archivos = @(Get-ChildItem -LiteralPath $Origen -Filter '*.log' -File -Recurse -ErrorAction Stop |
                Where-Object { $_.LastWriteTime -lt $hoy })
        $verificados = New-Object System.Collections.Generic.List[string]
        $copiados = 0; $yaExistian = 0; $fallidos = 0
        foreach ($a in $archivos) {
            $relativo = $a.FullName.Substring((Resolve-Path -LiteralPath $Origen).ProviderPath.TrimEnd('\').Length).TrimStart('\')
            $dest = Join-Path $Destino $relativo
            $hashOrigen = (Get-HashSha256 -Ruta $a.FullName)
            if ((Test-Path -LiteralPath $dest) -and (Get-HashSha256 -Ruta $dest) -eq $hashOrigen) {
                $yaExistian++; $verificados.Add($a.FullName); continue
            }
            if ($PSCmdlet.ShouldProcess($a.FullName, "Copiar a $dest")) {
                try {
                    $carpetaDest = Split-Path $dest -Parent
                    if (-not (Test-Path -LiteralPath $carpetaDest)) { New-Item -ItemType Directory -Path $carpetaDest -Force | Out-Null }
                    Copy-Item -LiteralPath $a.FullName -Destination $dest -Force -ErrorAction Stop
                    if ((Get-HashSha256 -Ruta $dest) -ne $hashOrigen) {
                        throw "El hash de la copia no coincide"
                    }
                    $copiados++; $verificados.Add($a.FullName)
                } catch {
                    $fallidos++
                    Write-LogMantenimiento -Nivel ERROR -Paso $paso -Mensaje "Fallo la copia de $($a.Name): $($_.Exception.Message)" -Datos @{ archivo = $a.FullName }
                }
            }
        }
        $datos = @{ candidatos = $archivos.Count; copiados = $copiados; ya_existian = $yaExistian; fallidos = $fallidos; destino = $Destino }
        $estado = if ($fallidos -gt 0) { 'ERROR' } else { 'OK' }
        Write-LogMantenimiento -Nivel $(if ($fallidos) { 'ERROR' } else { 'INFO' }) -Paso $paso -Mensaje "Copiados $copiados, ya existian $yaExistian, fallidos $fallidos" -Datos $datos
        $r = New-ResultadoPaso -Paso $paso -Estado $estado -Datos $datos
        $r | Add-Member -NotePropertyName Verificados -NotePropertyValue $verificados.ToArray()
        return $r
    } catch {
        Write-LogMantenimiento -Nivel ERROR -Paso $paso -Mensaje $_.Exception.Message -Datos @{ destino = $Destino }
        $r = New-ResultadoPaso -Paso $paso -Estado 'ERROR' -Mensaje $_.Exception.Message
        $r | Add-Member -NotePropertyName Verificados -NotePropertyValue @()
        return $r
    } finally {
        if ($unidad) { Remove-PSDrive -Name $unidad.Name -Force -ErrorAction SilentlyContinue -WhatIf:$false }
    }
}

# ------------------------------------------------------------------ retencion
function Remove-ArchivoAntiguo {
    <#
    .SYNOPSIS
        Borra archivos con mas de N dias en una carpeta, con salvaguardas.
    .PARAMETER SoloSiEstanEn
        Lista de rutas permitidas: solo se borra lo que aparezca aqui (p.ej. los logs
        cuya copia en auditoria se verifico). Si se pasa vacia, no se borra nada.
    .PARAMETER ConservarUltimos
        Nunca borra los N archivos mas recientes (p.ej. dumps para analisis).
    #>
    [CmdletBinding(SupportsShouldProcess)]
    param(
        [Parameter(Mandatory)][string]$Paso,
        [Parameter(Mandatory)][string]$Ruta,
        [Parameter(Mandatory)][string]$Filtro,
        [Parameter(Mandatory)][ValidateRange(0, 3650)][double]$Dias,
        [string[]]$SoloSiEstanEn,
        [ValidateRange(0, 1000)][int]$ConservarUltimos = 0,
        [switch]$Recursivo
    )
    if (-not (Test-Path -LiteralPath $Ruta -PathType Container)) {
        Write-LogMantenimiento -Nivel ADVERTENCIA -Paso $Paso -Mensaje "La carpeta no existe: $Ruta" -Datos @{ ruta = $Ruta }
        return New-ResultadoPaso -Paso $Paso -Estado 'ADVERTENCIA' -Mensaje "No existe $Ruta"
    }
    $limite = (Get-Date).AddDays(-$Dias)
    $todos = @(Get-ChildItem -LiteralPath $Ruta -Filter $Filtro -File -Recurse:$Recursivo -ErrorAction Stop |
            Sort-Object LastWriteTime -Descending)
    $protegidos = @($todos | Select-Object -First $ConservarUltimos)
    $candidatos = @($todos | Where-Object { $_.LastWriteTime -lt $limite -and $protegidos -notcontains $_ })
    if ($PSBoundParameters.ContainsKey('SoloSiEstanEn')) {
        $permitidos = @($SoloSiEstanEn)
        $sinRespaldo = @($candidatos | Where-Object { $permitidos -notcontains $_.FullName })
        $candidatos = @($candidatos | Where-Object { $permitidos -contains $_.FullName })
    } else { $sinRespaldo = @() }

    $borrados = 0; $bytes = [long]0; $fallidos = 0
    foreach ($a in $candidatos) {
        if ($PSCmdlet.ShouldProcess($a.FullName, 'Eliminar')) {
            try {
                $tam = $a.Length
                Remove-Item -LiteralPath $a.FullName -Force -ErrorAction Stop
                $borrados++; $bytes += $tam
            } catch {
                $fallidos++
                Write-LogMantenimiento -Nivel ERROR -Paso $Paso -Mensaje "No se pudo borrar $($a.Name): $($_.Exception.Message)" -Datos @{ archivo = $a.FullName }
            }
        }
    }
    $datos = @{ ruta = $Ruta; encontrados = $todos.Count; candidatos = $candidatos.Count; borrados = $borrados
        liberado_mb = [math]::Round($bytes / 1MB, 1); fallidos = $fallidos; sin_respaldo = $sinRespaldo.Count
        conservados_por_regla = $protegidos.Count }
    $estado = 'OK'
    if ($sinRespaldo.Count -gt 0) { $estado = 'ADVERTENCIA' }
    if ($fallidos -gt 0) { $estado = 'ERROR' }
    $nivel = @{ OK = 'INFO'; ADVERTENCIA = 'ADVERTENCIA'; ERROR = 'ERROR' }[$estado]
    $msg = "Borrados $borrados de $($candidatos.Count) candidatos ($($datos.liberado_mb) MB)"
    if ($sinRespaldo.Count) { $msg += "; $($sinRespaldo.Count) no se borran porque no tienen copia verificada" }
    Write-LogMantenimiento -Nivel $nivel -Paso $Paso -Mensaje $msg -Datos $datos
    New-ResultadoPaso -Paso $Paso -Estado $estado -Datos $datos -Mensaje $msg
}

function Get-DumpReciente {
    <# Cuenta volcados de memoria nuevos: si hay, el proceso se cayo y alguien debe saberlo. #>
    [CmdletBinding()]
    param([Parameter(Mandatory)][string]$Ruta, [int]$Horas = 24)
    if (-not (Test-Path -LiteralPath $Ruta)) {
        return New-ResultadoPaso -Paso 'dumps_recientes' -Datos @{ recientes = 0 } -Mensaje "Sin carpeta de dumps"
    }
    $recientes = @(Get-ChildItem -LiteralPath $Ruta -Filter '*.dmp' -File | Where-Object { $_.LastWriteTime -gt (Get-Date).AddHours(-$Horas) })
    $datos = @{ ruta = $Ruta; recientes = $recientes.Count; archivos = @($recientes | ForEach-Object Name) }
    if ($recientes.Count -gt 0) {
        Write-LogMantenimiento -Nivel ADVERTENCIA -Paso 'dumps_recientes' -Mensaje "$($recientes.Count) volcado(s) de memoria en las ultimas $Horas h: hubo caidas del proceso" -Datos $datos
        return New-ResultadoPaso -Paso 'dumps_recientes' -Estado 'ADVERTENCIA' -Datos $datos -Mensaje "$($recientes.Count) dumps recientes"
    }
    Write-LogMantenimiento -Nivel INFO -Paso 'dumps_recientes' -Mensaje "Sin volcados recientes" -Datos $datos
    New-ResultadoPaso -Paso 'dumps_recientes' -Datos $datos
}

# ---------------------------------------------------------------- servicios
function Assert-ServicioEnEjecucion {
    <# Arranca el servicio solo si esta detenido. No lo reinicia si ya funciona. #>
    [CmdletBinding(SupportsShouldProcess)]
    param([Parameter(Mandatory)][string]$Nombre)
    $paso = "servicio:$Nombre"
    $svc = Get-Service -Name $Nombre -ErrorAction SilentlyContinue
    if (-not $svc) {
        Write-LogMantenimiento -Nivel ERROR -Paso $paso -Mensaje "El servicio no existe" -Datos @{ servicio = $Nombre }
        return New-ResultadoPaso -Paso $paso -Estado 'ERROR' -Mensaje 'No existe'
    }
    if ($svc.Status -eq 'Running') {
        Write-LogMantenimiento -Nivel INFO -Paso $paso -Mensaje "En ejecucion; no se toca" -Datos @{ estado = 'Running' }
        return New-ResultadoPaso -Paso $paso -Datos @{ estado = 'Running'; accion = 'ninguna' }
    }
    if ($PSCmdlet.ShouldProcess($Nombre, 'Iniciar servicio detenido')) {
        try {
            Start-Service -Name $Nombre -ErrorAction Stop
            Write-LogMantenimiento -Nivel ADVERTENCIA -Paso $paso -Mensaje "Estaba $($svc.Status); se inicio" -Datos @{ estado_previo = "$($svc.Status)" }
            return New-ResultadoPaso -Paso $paso -Estado 'ADVERTENCIA' -Datos @{ estado_previo = "$($svc.Status)"; accion = 'iniciado' }
        } catch {
            Write-LogMantenimiento -Nivel ERROR -Paso $paso -Mensaje "No se pudo iniciar: $($_.Exception.Message)"
            return New-ResultadoPaso -Paso $paso -Estado 'ERROR' -Mensaje $_.Exception.Message
        }
    }
    New-ResultadoPaso -Paso $paso -Estado 'ADVERTENCIA' -Datos @{ estado_previo = "$($svc.Status)"; accion = 'simulado' }
}

# --------------------------------------------------------------------- IIS
function Get-EstadoPoolIIS {
    <#
    Solo informa: estado del pool y memoria privada de sus procesos w3wp.
    No reinicia nada: el reciclaje por memoria se configura en IIS y la
    auto-remediacion vive en Azure Monitor (Reto 3), con salvaguardas.
    #>
    [CmdletBinding()]
    param([Parameter(Mandatory)][string]$Pool, [int]$UmbralMemoriaMB = 1000)
    $paso = "pool:$Pool"
    if (-not (Get-Command Get-IISAppPool -ErrorAction SilentlyContinue)) {
        try { Import-Module IISAdministration -ErrorAction Stop } catch {
            Write-LogMantenimiento -Nivel ADVERTENCIA -Paso $paso -Mensaje "IIS no disponible en este equipo; paso omitido"
            return New-ResultadoPaso -Paso $paso -Estado 'OMITIDO' -Mensaje 'Sin modulo IISAdministration'
        }
    }
    $p = Get-IISAppPool -Name $Pool -ErrorAction SilentlyContinue
    if (-not $p) {
        Write-LogMantenimiento -Nivel ERROR -Paso $paso -Mensaje "El pool no existe"
        return New-ResultadoPaso -Paso $paso -Estado 'ERROR' -Mensaje 'No existe'
    }
    $procesos = @(Get-CimInstance Win32_Process -Filter "Name='w3wp.exe'" -ErrorAction SilentlyContinue |
            Where-Object { $_.CommandLine -match "-ap ""$([regex]::Escape($Pool))""" })
    # Sin procesos (pool detenido) Measure-Object no devuelve Sum en modo estricto: se suma a mano
    $bytes = [double]0
    foreach ($pr in $procesos) { $bytes += [double]$pr.PrivatePageCount }
    $memMB = [math]::Round($bytes / 1MB, 0)
    $datos = @{ estado = "$($p.State)"; procesos = $procesos.Count; memoria_privada_mb = $memMB; umbral_mb = $UmbralMemoriaMB }
    $estado = 'OK'; $nivel = 'INFO'
    if ("$($p.State)" -ne 'Started') { $estado = 'ERROR'; $nivel = 'ERROR' }
    elseif ($memMB -gt $UmbralMemoriaMB) { $estado = 'ADVERTENCIA'; $nivel = 'ADVERTENCIA' }
    Write-LogMantenimiento -Nivel $nivel -Paso $paso -Mensaje "Pool $($p.State), $memMB MB" -Datos $datos
    New-ResultadoPaso -Paso $paso -Estado $estado -Datos $datos
}

# ------------------------------------------------------------------ resumen
function Get-CodigoSalida {
    <#
    0 = todo OK (puede tener advertencias, que quedan en el log)
    1 = al menos un paso fallo
    2 = parametros o precondiciones invalidos (no se hizo nada)
    3 = otra ejecucion en curso (no se hizo nada)
    4 = error inesperado
    #>
    param([object[]]$Resultados)
    if (@($Resultados | Where-Object Estado -eq 'ERROR').Count -gt 0) { return 1 }
    0
}

Export-ModuleMember -Function Initialize-LogMantenimiento, Write-LogMantenimiento, Get-EstadoDisco,
    Copy-LogsAuditoria, Remove-ArchivoAntiguo, Get-DumpReciente, Assert-ServicioEnEjecucion,
    Get-EstadoPoolIIS, Get-CodigoSalida
