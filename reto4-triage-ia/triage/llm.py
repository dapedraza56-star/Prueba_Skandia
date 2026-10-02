"""Clientes de modelo de lenguaje.

Se usa la API de chat compatible con OpenAI porque la ofrecen GitHub Models,
Azure OpenAI / AI Foundry y otros: cambiar de proveedor es cambiar 3 variables
de entorno, no el codigo. La clave nunca esta en el codigo: se lee del entorno
(archivo .env local, ignorado por Git, o Key Vault en Azure).

Variables:
    TRIAGE_PROVEEDOR  github | azure | simulado         (por defecto github)
    TRIAGE_ENDPOINT   p.ej. https://models.github.ai/inference
    TRIAGE_MODELO     p.ej. openai/gpt-4.1-mini
    TRIAGE_API_KEY    token (en GitHub Models: token con permiso models:read)
    TRIAGE_TIMEOUT_S  segundos por llamada (por defecto 30)
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Protocol

import requests


class ErrorModelo(Exception):
    """El modelo no respondio a tiempo, devolvio un error o no esta configurado."""

    def __init__(self, motivo: str, detalle: str = ""):
        super().__init__(f"{motivo}: {detalle}" if detalle else motivo)
        self.motivo = motivo


class ClienteLLM(Protocol):
    modelo: str

    def completar(self, mensajes: list[dict]) -> str: ...


@dataclass
class ClienteOpenAICompatible:
    endpoint: str
    modelo: str
    api_key: str = field(repr=False)          # repr=False: nunca aparece en logs ni trazas
    encabezado_clave: str = "Authorization"   # Azure OpenAI usa "api-key"
    timeout_s: float = 30.0
    reintentos: int = 2

    def completar(self, mensajes: list[dict]) -> str:
        url = self.endpoint.rstrip("/") + "/chat/completions"
        valor = f"Bearer {self.api_key}" if self.encabezado_clave == "Authorization" else self.api_key
        cuerpo = {"model": self.modelo, "messages": mensajes, "temperature": 0,
                  "max_tokens": 1800, "response_format": {"type": "json_object"}}
        ultimo = ""
        for intento in range(self.reintentos + 1):
            try:
                r = requests.post(url, json=cuerpo, timeout=self.timeout_s,
                                  headers={self.encabezado_clave: valor, "Content-Type": "application/json"})
            except requests.Timeout as e:
                raise ErrorModelo("timeout", f"sin respuesta en {self.timeout_s:.0f} s") from e
            except requests.RequestException as e:
                raise ErrorModelo("red", type(e).__name__) from e
            if r.status_code == 200:
                try:
                    return r.json()["choices"][0]["message"]["content"] or ""
                except (KeyError, IndexError, ValueError) as e:
                    raise ErrorModelo("respuesta_malformada", r.text[:200]) from e
            ultimo = f"HTTP {r.status_code}"
            if r.status_code in (429, 500, 502, 503, 504) and intento < self.reintentos:
                espera = min(float(r.headers.get("Retry-After", 2 ** intento)), 10.0)
                time.sleep(espera)
                continue
            # 4xx: no tiene sentido reintentar (clave invalida, modelo inexistente, contenido filtrado)
            raise ErrorModelo("http", f"{ultimo} {r.text[:200]}")
        raise ErrorModelo("http", ultimo)


class ClienteSimulado:
    """Devuelve respuestas predefinidas (texto o excepcion). Para pruebas y demos sin red."""

    modelo = "simulado"

    def __init__(self, respuestas: list):
        self.respuestas = list(respuestas)
        self.llamadas: list[list[dict]] = []

    def completar(self, mensajes):
        self.llamadas.append(mensajes)
        if not self.respuestas:
            raise ErrorModelo("simulado_sin_respuestas")
        r = self.respuestas.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def cliente_desde_entorno() -> ClienteLLM:
    proveedor = os.getenv("TRIAGE_PROVEEDOR", "github").lower()
    if proveedor == "simulado":
        raise ErrorModelo("configuracion", "el proveedor simulado solo se usa en pruebas")
    clave = os.getenv("TRIAGE_API_KEY") or os.getenv("GITHUB_TOKEN")
    if not clave:
        raise ErrorModelo("configuracion", "falta TRIAGE_API_KEY (ver .env.ejemplo)")
    if proveedor == "azure":
        return ClienteOpenAICompatible(
            endpoint=os.environ["TRIAGE_ENDPOINT"], modelo=os.environ["TRIAGE_MODELO"], api_key=clave,
            encabezado_clave="api-key", timeout_s=float(os.getenv("TRIAGE_TIMEOUT_S", "30")))
    return ClienteOpenAICompatible(
        endpoint=os.getenv("TRIAGE_ENDPOINT", "https://models.github.ai/inference"),
        modelo=os.getenv("TRIAGE_MODELO", "openai/gpt-4.1-mini"), api_key=clave,
        timeout_s=float(os.getenv("TRIAGE_TIMEOUT_S", "30")))
