@echo off
REM ============================================================
REM  Mantenimiento diario WEB-PAGOS-01
REM  Tarea programada: \Mantenimiento\MantenimientoDiarioIIS  (02:00 todos los dias)
REM  Invocacion: C:\scripts\mantenimiento_diario.bat D:\logs\iis
REM  Autor: soporte 2019 - no tocar, funciona
REM ============================================================
set LOGDIR=%1
set DIAS=7
set CRASHDIR=C:\Dumps

echo Iniciando mantenimiento %date% %time%

REM 1. borrar logs viejos
forfiles /p %LOGDIR% /s /m *.log /d -%DIAS% /c "cmd /c del @path"

REM 2. borrar temporales
del /q /s %LOGDIR%\*.tmp

REM 3. borrar dumps (ocupan mucho)
del /q %CRASHDIR%\*.*

REM 4. reiniciar IIS para liberar memoria (la app se pone lenta si no)
iisreset /restart

REM 5. reiniciar servicio de notificaciones
net stop "Servicio Notificaciones"
net start "Servicio Notificaciones"

REM 6. copiar logs al share de auditoria
net use Z: \\fs-auditoria\logs$ /user:ANDINA\svc_mantenimiento Andina2019*
xcopy %LOGDIR%\*.log Z:\WEB-PAGOS-01\ /s /y
net use Z: /delete

echo Proceso OK >> C:\scripts\mantenimiento.log
exit /b 0
