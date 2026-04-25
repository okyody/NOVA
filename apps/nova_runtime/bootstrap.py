"""Shared runtime bootstrap helpers for API and worker roles."""

from __future__ import annotations

import os
import socket
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from apps.nova_server.main import NovaApp


@dataclass(frozen=True)
class RolePlan:
    role: str
    run_bus: bool
    run_perception: bool
    run_cognitive: bool
    run_generation: bool
    run_platform_ingress: bool


def build_role_plan(role: str) -> RolePlan:
    return RolePlan(
        role=role,
        run_bus=role in {"all", "perception", "cognitive", "generation"},
        run_perception=role in {"all", "perception"},
        run_cognitive=role in {"all", "cognitive"},
        run_generation=role in {"all", "generation"},
        run_platform_ingress=role in {"all", "perception"},
    )


def configure_worker_environment(role: str) -> None:
    os.environ["NOVA_RUNTIME__ROLE"] = role
    os.environ.setdefault("NOVA_RUNTIME__EVENT_BUS_MODE", "external_consumer")
    os.environ.setdefault("NOVA_RUNTIME__EVENT_BUS_BACKEND", "redis_streams")
    os.environ.setdefault("NOVA_PERSIST__ENABLED", "true")
    os.environ.setdefault("NOVA_PERSIST__BACKEND", "redis")

    hostname = socket.gethostname().lower().replace(".", "-")
    consumer_group_map = {
        "perception": "nova-perception",
        "cognitive": "nova-cognitive",
        "generation": "nova-generation",
    }
    group = consumer_group_map.get(role, "nova-workers")
    os.environ.setdefault("NOVA_RUNTIME__EVENT_BUS_CONSUMER_GROUP", group)
    os.environ.setdefault("NOVA_RUNTIME__EVENT_BUS_CONSUMER_NAME", f"{group}-{hostname}")
    os.environ.setdefault("NOVA_RUNTIME__INSTANCE_NAME", f"{role}-{hostname}")
    os.environ.setdefault("NOVA_RUNTIME__SESSION_ID", "primary")


def create_worker_app(role: str) -> "NovaApp":
    configure_worker_environment(role)

    from packages.core.config import load_settings
    from apps.nova_server.main import NovaApp

    settings = load_settings()
    return NovaApp(settings)
