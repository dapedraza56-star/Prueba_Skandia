# Reto 1 · Diagnóstico basado en datos

| Entregable | Archivo |
|---|---|
| Post-mortem para la Directora (máximo 3 páginas) | [postmortem.md](postmortem.md) |
| Código reproducible | [src/carga.py](src/carga.py) (lectura y limpieza) y [src/analisis.py](src/analisis.py) (análisis, modelos y gráficas) |
| Resultados con todas las cifras y su evidencia | [salidas/resultados.md](salidas/resultados.md) |
| Tablas | `salidas/linea_tiempo.csv`, `salidas/disponibilidad.csv`, `salidas/senales_tempranas.csv` |
| Gráficas | `salidas/fig1_incidente_18sep.png`, `salidas/fig2_semana_memoria_disco.png`, `salidas/fig3_fuga_memoria.png` |
| Pruebas | [tests/test_carga.py](tests/test_carga.py) |

## Cómo reproducirlo

Desde la raíz del repositorio, con Python 3.12 o superior:

```bash
python -m venv .venv
```

```bash
.venv/Scripts/python -m pip install -r requirements.txt
```

```bash
.venv/Scripts/python reto1-diagnostico/src/analisis.py
```

```bash
.venv/Scripts/python -m pytest reto1-diagnostico/tests -q
```

El análisis tarda unos 15 segundos y regenera todo `salidas/`. En Linux o macOS usa `.venv/bin/python`.

## Método

1. **Limpieza** (`carga.py`):
   - Conversión de UTC a hora de Colombia.
   - Lectura W3C que respeta cada directiva `#Fields`.
   - Descarte de archivos duplicados por hash.
   - Separación de usuarios reales, del sondeo del NOC y de los escáneres.
   - Unión de IIS con HTTP.sys, porque los 503 de la caída solo existen en `httperr1.log`.
2. **Línea de tiempo:** cruce de eventos de Windows, latencia p95 cada 10 minutos, primer 500, 503 de HTTP.sys y tickets. Cada fila cita archivo y línea.
3. **Disponibilidad:** se calcula de dos formas:
   - Por operación: porcentaje de peticiones sin 5xx.
   - Por tiempo: una ventana de 5 minutos cuenta como no disponible si tiene más de 5 % de errores y al menos 3 fallas.

   Las dos se comparan con lo que ve el sondeo `/health` del NOC.
4. **Modelo de memoria:** regresión lineal (OLS) de `Private Bytes` de w3wp contra los pagos confirmados acumulados desde el reinicio de las 02:00. Se probaron tres predictores; el elegido explica el 99,9 % de la variación.
5. **Pronóstico de disco:** OLS del consumo horario de disco contra las peticiones, desde el 16/09 y sin la hora de los volcados de memoria. Se proyecta con tres perfiles de tráfico observados (fin de semana, lunes a jueves y viernes 18/09), porque la incertidumbre está en la demanda y no en el coeficiente.

## Supuestos

| # | Supuesto | Por qué |
|---|---|---|
| S1 | Los logs de IIS y HTTP.sys están en UTC; eventos y Perfmon, en hora local | Comportamiento por defecto de IIS. Lo confirman el `#Date` del 14/09 (05:00) y que `u_ex260921.log` termina a las 04:59 UTC |
| S2 | Colombia es UTC-5 todo el año | No tiene horario de verano |
| S3 | Los archivos estáticos (`/static/*`, `favicon.ico`) no cuentan en la disponibilidad | Las fallas que importan son las operaciones del cliente |
| S4 | Escáneres: agente `zgrab` y rutas `/.env`, `/wp-login.php`, `/phpmyadmin/index.php`, `/admin/config.php` | Ticket T-10236; ningún usuario legítimo pide esas rutas |
| S5 | En `httperr1.log` el sondeo del NOC se identifica por la URI `/health` | HTTP.sys no registra el User-Agent |
| S6 | Latencia "degradada" = p95 por encima de 1,5 veces la línea base (lunes a martes, 08–17 h, antes del despliegue). "Fuerte" = p95 > 3 s | Umbral operativo propio, documentado |
| S7 | El umbral de OutOfMemory es la memoria máxima medida antes del primer crash (~1.478 MB) | Es lo observado; la causa del límite es la hipótesis P2 del post-mortem |
| S8 | El pronóstico de disco supone que nada cambia: el log sigue en Debug y no se limpia | Es el escenario "si no hacemos nada" |

## Limitaciones conocidas

- La exportación de eventos no incluye el reinicio manual de las 15:04. Esa hora sale del ticket.
- Durante la caída total, HTTP.sys registra la IP del balanceador, no la del cliente. Por eso los "463 clientes afectados" son un mínimo.
- El conteo de peticiones subestima el impacto: los clientes que abandonaron el portal no aparecen en ningún log.
- Los datos son sintéticos y algunos ajustes son casi perfectos (R² cercano a 1,00). Con datos reales se esperaría más dispersión y habría que reportar intervalos de confianza.
