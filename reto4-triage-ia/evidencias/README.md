# Evidencias del Reto 4

Esta carpeta guarda los resultados de los casos con el modelo real, que genera `casos/ejecutar_casos.py`:

- `resumen_casos.md`: tabla de los casos A a E (estado, intentos, errores detectados, runbook sugerido, confianza y latencia) y la lista de errores que detectó el validador;
- `caso_A.json` … `caso_E.json`: el resultado completo de cada caso (triage, `meta` y contexto enviado al modelo).

**Estado:** pendiente de ejecutar con un token de GitHub Models (ver la sección 5 del README del reto). Mientras tanto, la detección de invenciones está demostrada por las pruebas con modelo simulado (`tests/test_triage.py`).
