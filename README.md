# Prueba técnica · Especialista en Observabilidad y Automatización

Solución al caso **PortalPagos** de Andina Financiera, una empresa ficticia con datos sintéticos.

| Reto | Carpeta | Estado |
|---|---|---|
| 1 · Diagnóstico basado en datos | [reto1-diagnostico/](reto1-diagnostico/) | ✅ Análisis, pruebas y post-mortem |
| 2 · Modernizar el mantenimiento | [reto2-powershell/](reto2-powershell/) | ✅ Script, 31 pruebas Pester (5.1 y 7) y demo. Falta la evidencia en la VM (Reto 3) |
| 3 · Observabilidad y auto-remediación en Azure | `reto3-azure/` | Pendiente |
| 4 · IA para el triage de incidentes | `reto4-triage-ia/` | Pendiente |
| 5 · Propuesta de 90 días | `reto5-propuesta/` | Pendiente |
| Bitácora de IA | [IA_BITACORA.md](IA_BITACORA.md) | En curso |

## Requisitos

- Python 3.12 o superior (probado con 3.14)
- PowerShell 5.1 y 7, con Pester 5 o superior (Reto 2)
- Azure CLI con Bicep y una suscripción propia (Reto 3)

```bash
python -m venv .venv
```

```bash
.venv/Scripts/python -m pip install -r requirements.txt
```

Cada reto tiene su propio README con los pasos para reproducirlo y sus supuestos.

## Datos

`kit_prueba_portalpagos/` es el kit entregado, sin modificar. El código lo lee tal cual y toda la limpieza ocurre en el código, nunca a mano.

## Seguridad

No hay secretos en el repositorio. Las claves van en `.env` (ignorado por Git) o en Azure Key Vault. Antes de cada push se revisa con `gitleaks detect`.
