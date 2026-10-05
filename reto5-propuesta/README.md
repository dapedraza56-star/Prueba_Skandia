# Reto 5 · Propuesta para los primeros 90 días

| Entregable | Archivo |
|---|---|
| Propuesta (máximo 2 páginas), fuente editable | [propuesta_90_dias.md](propuesta_90_dias.md) |
| Versión para leer o imprimir (paleta Skandia) | `propuesta_90_dias.pdf` y `propuesta_90_dias.html` |
| Generador del HTML y PDF, que además verifica el límite de 2 páginas | [generar_documento.py](generar_documento.py) |

Para regenerar el documento después de editar el `.md`:

```bash
.venv/Scripts/python reto5-propuesta/generar_documento.py
```

El PDF se imprime con Microsoft Edge en modo headless. Si la propuesta supera 2 páginas, el script termina con error.

Todas las líneas base de la sección 2 salen del análisis del Reto 1:
- MTTD de 79 min y MTTR de 101 min, medidos desde el primer error de las 13:23.
- Disponibilidad real de 98,46 %, frente al 100 % reportado por el NOC.
- 0 % de incidentes detectados antes que el usuario.
- La alerta de 5xx habría detectado el incidente en la ventana de las 13:20 a 13:25, frente al primer ticket de las 13:34.

Las horas de trabajo manual no se pueden medir con el kit, así que la propuesta las deja como "por medir en las semanas 1 y 2" en lugar de inventar una cifra.
