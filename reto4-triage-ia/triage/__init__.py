"""Triage de incidentes asistido por IA (Reto 4). Sugiere; una persona decide."""
from .contexto import Alerta, Elemento, FuenteKit, construir_contexto
from .motor import ejecutar_triage

__all__ = ["Alerta", "Elemento", "FuenteKit", "construir_contexto", "ejecutar_triage"]
