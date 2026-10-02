#Requires -Modules @{ ModuleName = 'Pester'; ModuleVersion = '5.0' }
<#
    Pruebas del mantenimiento de PortalPagos.
    Ejecutar:  Invoke-Pester ./reto2-powershell/tests -Output Detailed
    Corren en Windows PowerShell 5.1 y en PowerShell 7, sin IIS ni privilegios de administrador:
    todo ocurre en carpetas temporales (TestDrive) y los cmdlets de servicios/IIS se simulan.
#>

BeforeAll {
    $script:Src = Join-Path $PSScriptRoot '..\src'
    $script:Script = Join-Path $Src 'Invoke-MantenimientoPortal.ps1'
    Import-Module (Join-Path $Src 'MantenimientoPortal.psm1') -Force

    function New-ArchivoConFecha([string]$Ruta, [datetime]$Fecha, [string]$Contenido = 'x') {
        $carpeta = Split-Path $Ruta -Parent
        if (-not (Test-Path $carpeta)) { New-Item -ItemType Directory -Path $carpeta -Force | Out-Null }
        Set-Content -LiteralPath $Ruta -Value $Contenido
        (Get-Item -LiteralPath $Ruta).LastWriteTime = $Fecha
    }

    function Invoke-ScriptHijo([hashtable]$Parametros, [switch]$WhatIf) {
        # Ejecuta el script en un proceso aparte (como la tarea programada) y devuelve el codigo de salida
        $motor = (Get-Process -Id $PID).Path
        $lista = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $script:Script)
        foreach ($k in $Parametros.Keys) {
            $v = $Parametros[$k]
            if ($v -is [array]) { $lista += "-$k"; $lista += ($v -join ',') } else { $lista += "-$k"; $lista += "$v" }
        }
        if ($WhatIf) { $lista += '-WhatIf' }
        $null = & $motor @lista 2>&1
        $LASTEXITCODE
    }
}

Describe 'Log estructurado' {
    It 'escribe una linea JSON valida por evento, con los campos esperados' {
        $log = Join-Path $TestDrive 'log\m.jsonl'
        Initialize-LogMantenimiento -Ruta $log -IdEjecucion 'prueba-1'
        Write-LogMantenimiento -Nivel INFO -Paso 'p1' -Mensaje 'hola' -Datos @{ n = 3 }
        Write-LogMantenimiento -Nivel ERROR -Paso 'p2' -Mensaje 'fallo'
        $lineas = Get-Content $log
        $lineas.Count | Should -Be 2
        $o = $lineas[0] | ConvertFrom-Json
        $o.nivel | Should -Be 'INFO'
        $o.ejecucion | Should -Be 'prueba-1'
        $o.datos.n | Should -Be 3
        { [datetimeoffset]::Parse($o.ts) } | Should -Not -Throw
    }

    It 'escribe UTF-8 sin BOM, para que la primera linea sea JSON valido al ingerirla' {
        $log = Join-Path $TestDrive 'sin-bom.jsonl'
        Initialize-LogMantenimiento -Ruta $log
        Write-LogMantenimiento -Nivel INFO -Paso 'p' -Mensaje 'contraseña con tilde: ñ á'
        $bytes = [System.IO.File]::ReadAllBytes($log)
        ($bytes[0] -eq 0xEF -and $bytes[1] -eq 0xBB) | Should -BeFalse
        ([System.IO.File]::ReadAllText($log) | ConvertFrom-Json).mensaje | Should -Be 'contraseña con tilde: ñ á'
    }
}

Describe 'Copy-LogsAuditoria' {
    BeforeEach {
        $origen = Join-Path $TestDrive "origen-$([guid]::NewGuid())"
        $destino = Join-Path $TestDrive "auditoria-$([guid]::NewGuid())"
        Initialize-LogMantenimiento -Ruta (Join-Path $TestDrive 'copia.jsonl')
        New-ArchivoConFecha (Join-Path $origen 'u_ex260901.log') (Get-Date).AddDays(-20) 'viejo'
        New-ArchivoConFecha (Join-Path $origen 'u_ex260920.log') (Get-Date).AddDays(-1) 'ayer'
        New-ArchivoConFecha (Join-Path $origen 'u_exHOY.log') (Get-Date) 'abierto por IIS'
    }

    It 'copia y verifica los logs cerrados, pero no el del dia en curso' {
        $r = Copy-LogsAuditoria -Origen $origen -Destino $destino
        $r.Estado | Should -Be 'OK'
        $r.Datos.copiados | Should -Be 2
        $r.Verificados.Count | Should -Be 2
        Test-Path (Join-Path $destino 'u_exHOY.log') | Should -BeFalse
    }

    It 'es idempotente: la segunda ejecucion no vuelve a copiar' {
        Copy-LogsAuditoria -Origen $origen -Destino $destino | Out-Null
        $r = Copy-LogsAuditoria -Origen $origen -Destino $destino
        $r.Datos.copiados | Should -Be 0
        $r.Datos.ya_existian | Should -Be 2
        $r.Verificados.Count | Should -Be 2
    }

    It 'vuelve a copiar si el archivo de auditoria es distinto (copia corrupta)' {
        Copy-LogsAuditoria -Origen $origen -Destino $destino | Out-Null
        Set-Content (Join-Path $destino 'u_ex260901.log') 'corrupto'
        (Copy-LogsAuditoria -Origen $origen -Destino $destino).Datos.copiados | Should -Be 1
    }

    It 'con -WhatIf no copia nada' {
        $r = Copy-LogsAuditoria -Origen $origen -Destino $destino -WhatIf
        Test-Path $destino | Should -BeFalse
        $r.Verificados.Count | Should -Be 0
    }

    It 'si el destino no es accesible devuelve ERROR y ninguna copia verificada' {
        Mock -ModuleName MantenimientoPortal Copy-Item { throw 'Acceso denegado' }
        $r = Copy-LogsAuditoria -Origen $origen -Destino $destino
        $r.Estado | Should -Be 'ERROR'
        $r.Verificados.Count | Should -Be 0
    }
}

Describe 'Remove-ArchivoAntiguo' {
    BeforeEach {
        $carpeta = Join-Path $TestDrive "ret-$([guid]::NewGuid())"
        Initialize-LogMantenimiento -Ruta (Join-Path $TestDrive 'ret.jsonl')
        $viejo = Join-Path $carpeta 'viejo.log'
        $viejo2 = Join-Path $carpeta 'viejo2.log'
        $nuevo = Join-Path $carpeta 'nuevo.log'
        New-ArchivoConFecha $viejo (Get-Date).AddDays(-40)
        New-ArchivoConFecha $viejo2 (Get-Date).AddDays(-35)
        New-ArchivoConFecha $nuevo (Get-Date).AddDays(-2)
    }

    It 'borra solo los archivos mas antiguos que la retencion' {
        $r = Remove-ArchivoAntiguo -Paso t -Ruta $carpeta -Filtro '*.log' -Dias 30
        $r.Datos.borrados | Should -Be 2
        Test-Path $nuevo | Should -BeTrue
    }

    It 'no borra logs viejos sin copia verificada en auditoria' {
        $r = Remove-ArchivoAntiguo -Paso t -Ruta $carpeta -Filtro '*.log' -Dias 30 -SoloSiEstanEn @($viejo)
        $r.Datos.borrados | Should -Be 1
        $r.Datos.sin_respaldo | Should -Be 1
        $r.Estado | Should -Be 'ADVERTENCIA'
        Test-Path $viejo2 | Should -BeTrue
    }

    It 'si la copia a auditoria fallo por completo (lista vacia), no borra nada' {
        $r = Remove-ArchivoAntiguo -Paso t -Ruta $carpeta -Filtro '*.log' -Dias 30 -SoloSiEstanEn @()
        $r.Datos.borrados | Should -Be 0
        (Get-ChildItem $carpeta).Count | Should -Be 3
    }

    It 'conserva siempre los N mas recientes (dumps para analisis) aunque sean viejos' {
        $r = Remove-ArchivoAntiguo -Paso dumps -Ruta $carpeta -Filtro '*.log' -Dias 1 -ConservarUltimos 2
        $r.Datos.borrados | Should -Be 1
        Test-Path $viejo | Should -BeFalse
        Test-Path $viejo2 | Should -BeTrue
    }

    It 'con -WhatIf no borra nada' {
        Remove-ArchivoAntiguo -Paso t -Ruta $carpeta -Filtro '*.log' -Dias 30 -WhatIf | Out-Null
        (Get-ChildItem $carpeta).Count | Should -Be 3
    }

    It 'si la carpeta no existe advierte sin lanzar error (no borra en otra ruta)' {
        { Remove-ArchivoAntiguo -Paso t -Ruta (Join-Path $TestDrive 'D-retirada') -Filtro '*.log' -Dias 1 } | Should -Not -Throw
        (Remove-ArchivoAntiguo -Paso t -Ruta (Join-Path $TestDrive 'D-retirada') -Filtro '*.log' -Dias 1).Estado |
            Should -Be 'ADVERTENCIA'
    }

    It 'es idempotente: la segunda ejecucion no encuentra nada que borrar' {
        Remove-ArchivoAntiguo -Paso t -Ruta $carpeta -Filtro '*.log' -Dias 30 | Out-Null
        (Remove-ArchivoAntiguo -Paso t -Ruta $carpeta -Filtro '*.log' -Dias 30).Datos.borrados | Should -Be 0
    }
}

Describe 'Get-DumpReciente' {
    It 'advierte cuando hay volcados nuevos (hubo caidas del proceso)' {
        $c = Join-Path $TestDrive 'dumps'
        New-ArchivoConFecha (Join-Path $c 'w3wp.exe.4471.dmp') (Get-Date).AddHours(-3)
        $r = Get-DumpReciente -Ruta $c
        $r.Estado | Should -Be 'ADVERTENCIA'
        $r.Datos.recientes | Should -Be 1
    }
}

Describe 'Assert-ServicioEnEjecucion' {
    BeforeAll { Initialize-LogMantenimiento -Ruta (Join-Path $TestDrive 'svc.jsonl') }

    It 'no reinicia un servicio que ya esta en ejecucion' {
        Mock -ModuleName MantenimientoPortal Get-Service { [pscustomobject]@{ Status = 'Running' } }
        Mock -ModuleName MantenimientoPortal Start-Service { }
        (Assert-ServicioEnEjecucion -Nombre 'Servicio Notificaciones').Datos.accion | Should -Be 'ninguna'
        Should -Invoke -ModuleName MantenimientoPortal Start-Service -Times 0
    }

    It 'inicia el servicio solo si esta detenido' {
        Mock -ModuleName MantenimientoPortal Get-Service { [pscustomobject]@{ Status = 'Stopped' } }
        Mock -ModuleName MantenimientoPortal Start-Service { }
        (Assert-ServicioEnEjecucion -Nombre 'Servicio Notificaciones').Datos.accion | Should -Be 'iniciado'
        Should -Invoke -ModuleName MantenimientoPortal Start-Service -Times 1
    }

    It 'con -WhatIf no inicia el servicio' {
        Mock -ModuleName MantenimientoPortal Get-Service { [pscustomobject]@{ Status = 'Stopped' } }
        Mock -ModuleName MantenimientoPortal Start-Service { }
        Assert-ServicioEnEjecucion -Nombre 'Servicio Notificaciones' -WhatIf | Out-Null
        Should -Invoke -ModuleName MantenimientoPortal Start-Service -Times 0
    }

    It 'si el servicio no existe devuelve ERROR' {
        Mock -ModuleName MantenimientoPortal Get-Service { $null }
        (Assert-ServicioEnEjecucion -Nombre 'NoExiste').Estado | Should -Be 'ERROR'
    }
}

Describe 'Get-EstadoPoolIIS' {
    BeforeAll {
        Initialize-LogMantenimiento -Ruta (Join-Path $TestDrive 'iis.jsonl')
        # Stub para poder simular IIS en equipos sin el rol instalado
        if (-not (Get-Command Get-IISAppPool -ErrorAction SilentlyContinue)) {
            function global:Get-IISAppPool { param($Name) }
        }
    }
    AfterAll { Remove-Item function:global:Get-IISAppPool -ErrorAction SilentlyContinue }

    It 'reporta ERROR si el pool esta detenido (como el 18/09 a las 14:38)' {
        Mock -ModuleName MantenimientoPortal Get-IISAppPool { [pscustomobject]@{ State = 'Stopped' } }
        Mock -ModuleName MantenimientoPortal Get-CimInstance { @() }
        (Get-EstadoPoolIIS -Pool 'PortalPagosPool').Estado | Should -Be 'ERROR'
    }

    It 'advierte si la memoria del pool supera el umbral, sin reiniciarlo' {
        Mock -ModuleName MantenimientoPortal Get-IISAppPool { [pscustomobject]@{ State = 'Started' } }
        Mock -ModuleName MantenimientoPortal Get-CimInstance {
            [pscustomobject]@{ CommandLine = 'w3wp.exe -ap "PortalPagosPool" -v v4.0'; PrivatePageCount = 1200MB }
        }
        $r = Get-EstadoPoolIIS -Pool 'PortalPagosPool' -UmbralMemoriaMB 1000
        $r.Estado | Should -Be 'ADVERTENCIA'
        $r.Datos.memoria_privada_mb | Should -Be 1200
    }
}

Describe 'Get-CodigoSalida' {
    It 'devuelve 0 con advertencias y 1 si algun paso fallo' {
        Get-CodigoSalida -Resultados @([pscustomobject]@{ Estado = 'OK' }, [pscustomobject]@{ Estado = 'ADVERTENCIA' }) | Should -Be 0
        Get-CodigoSalida -Resultados @([pscustomobject]@{ Estado = 'OK' }, [pscustomobject]@{ Estado = 'ERROR' }) | Should -Be 1
    }
}

Describe 'Script completo (como lo ejecuta la tarea programada)' {
    BeforeEach {
        $base = Join-Path $TestDrive "int-$([guid]::NewGuid())"
        $logs = Join-Path $base 'inetpub\logs\W3SVC2'
        $aud = Join-Path $base 'auditoria'
        $dumps = Join-Path $base 'CrashDumps'
        $logJson = Join-Path $base 'mantenimiento.jsonl'
        New-ArchivoConFecha (Join-Path $logs 'u_ex260801.log') (Get-Date).AddDays(-45) 'agosto'
        New-ArchivoConFecha (Join-Path $logs 'u_ex260919.log') (Get-Date).AddDays(-2) 'reciente'
        New-ArchivoConFecha (Join-Path $dumps 'w3wp.exe.1.dmp') (Get-Date).AddDays(-30)
        New-ArchivoConFecha (Join-Path $dumps 'w3wp.exe.2.dmp') (Get-Date).AddDays(-1)
        $p = @{ RutaLogsIIS = $logs; RutaAuditoria = $aud; RutaDumps = $dumps; RutaLog = $logJson
            DumpsAConservar = 1; ServiciosRequeridos = 'Winmgmt'; UmbralDiscoPorcentaje = 1 }
    }

    It 'termina con codigo 2 y no toca nada si la carpeta de logs no existe (caso D: retirada)' {
        $p.RutaLogsIIS = Join-Path $base 'D\logs\iis'
        Invoke-ScriptHijo $p | Should -Be 2
        Test-Path $aud | Should -BeFalse
        (Get-ChildItem $dumps).Count | Should -Be 2
        (Get-Content $logJson | ConvertFrom-Json | Where-Object paso -eq 'precondiciones').nivel | Should -Be 'ERROR'
    }

    It 'con -WhatIf termina en 0, no modifica archivos y lo deja registrado' {
        Invoke-ScriptHijo $p -WhatIf | Should -Be 0
        Test-Path (Join-Path $logs 'u_ex260801.log') | Should -BeTrue
        Test-Path $aud | Should -BeFalse
        (Get-ChildItem $dumps).Count | Should -Be 2
        @(Get-Content $logJson | ConvertFrom-Json | Where-Object { -not $_.simulacion }).Count | Should -Be 0
    }

    It 'archiva antes de borrar, conserva el dump mas reciente y termina en 0' {
        Invoke-ScriptHijo $p | Should -Be 0
        Test-Path (Join-Path $aud "$env:COMPUTERNAME\u_ex260801.log") | Should -BeTrue
        Test-Path (Join-Path $logs 'u_ex260801.log') | Should -BeFalse
        Test-Path (Join-Path $logs 'u_ex260919.log') | Should -BeTrue
        Test-Path (Join-Path $dumps 'w3wp.exe.2.dmp') | Should -BeTrue
        Test-Path (Join-Path $dumps 'w3wp.exe.1.dmp') | Should -BeFalse
    }

    It 'se puede ejecutar dos veces seguidas sin efectos no deseados' {
        Invoke-ScriptHijo $p | Should -Be 0
        Invoke-ScriptHijo $p | Should -Be 0
        $copias = Get-Content $logJson | ConvertFrom-Json | Where-Object paso -eq 'auditoria'
        $copias[-1].datos.copiados | Should -Be 0
        Test-Path (Join-Path $logs 'u_ex260919.log') | Should -BeTrue
    }

    It 'termina con codigo 1 si un paso falla (servicio inexistente) y el log lo explica' {
        $p.ServiciosRequeridos = 'ServicioQueNoExiste123'
        Invoke-ScriptHijo $p | Should -Be 1
        $fin = Get-Content $logJson | ConvertFrom-Json | Where-Object paso -eq 'fin'
        $fin.datos.codigo | Should -Be 1
    }

    It 'termina con codigo 3 si ya hay otra ejecucion en curso' {
        $m = New-Object System.Threading.Mutex($false, 'Global\MantenimientoPortalPagos')
        $m.WaitOne(0) | Should -BeTrue
        try { Invoke-ScriptHijo $p | Should -Be 3 } finally { $m.ReleaseMutex(); $m.Dispose() }
    }
}

Describe 'Seguridad y calidad del codigo' {
    It 'no contiene credenciales ni mapeos con contraseña' {
        $codigo = Get-ChildItem $Src -Include *.ps1, *.psm1 -Recurse | Get-Content -Raw
        $codigo | Should -Not -Match 'Andina2019'
        $codigo | Should -Not -Match 'ConvertTo-SecureString\s+.*-AsPlainText'
        $comandos = foreach ($f in Get-ChildItem $Src -Include *.ps1, *.psm1 -Recurse) {
            $ast = [System.Management.Automation.Language.Parser]::ParseFile($f.FullName, [ref]$null, [ref]$null)
            $ast.FindAll({ param($n) $n -is [System.Management.Automation.Language.CommandAst] }, $true) |
                ForEach-Object { $_.GetCommandName() }
        }
        $comandos | Should -Not -Contain 'net'
        $comandos | Should -Not -Contain 'net.exe'
    }

    It 'no reinicia IIS ni servicios (analiza los comandos reales, no los comentarios)' {
        $comandos = foreach ($f in Get-ChildItem $Src -Include *.ps1, *.psm1 -Recurse) {
            $ast = [System.Management.Automation.Language.Parser]::ParseFile($f.FullName, [ref]$null, [ref]$null)
            $ast.FindAll({ param($n) $n -is [System.Management.Automation.Language.CommandAst] }, $true) |
                ForEach-Object { $_.GetCommandName() }
        }
        $comandos | Should -Not -Contain 'iisreset'
        $comandos | Should -Not -Contain 'Restart-WebAppPool'
        $comandos | Should -Not -Contain 'Restart-Service'
        $comandos | Should -Not -Contain 'Stop-Service'
    }

    It 'pasa PSScriptAnalyzer sin errores ni advertencias' -Skip:(-not (Get-Module -ListAvailable PSScriptAnalyzer)) {
        $hallazgos = Invoke-ScriptAnalyzer -Path $Src -Recurse -Severity Error, Warning `
            -ExcludeRule PSAvoidUsingWriteHost
        $hallazgos | ForEach-Object { "$($_.ScriptName):$($_.Line) $($_.RuleName) $($_.Message)" } | Should -BeNullOrEmpty
    }
}
