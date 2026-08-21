# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The ``bunny-os model`` command group: the runtime side of the model bridge.

The brief sketches these as ``bunny model …``. This repository's management CLI
is ``bunny-os``, so they attach there rather than adding a second front-end:

    bunny model list              ->  bunny-os model list
    bunny model validate <path>   ->  bunny-os model validate <path>
    bunny model inspect <id>      ->  bunny-os model inspect <id>
    bunny model enable <id>       ->  bunny-os model enable <id>
    bunny model disable <id>      ->  bunny-os model disable <id>

Note which CLI this is. ``bunny-model`` — the Model Studio command — is a
repository-side developer tool that is deliberately **not** installed, because
it carries training code. This one is installed, because it carries none: it
imports :mod:`companion.models` and nothing from Model Studio, which
``tests/model_bridge/test_build_isolation.py`` asserts.

**These commands do not bypass anything.** ``enable`` runs the full validator,
digests included, and then asks the backend to apply and confirm; it cannot
activate a model the runtime would refuse. There is no ``--force``, no
``--skip-validation`` and no flag that turns a FAIL into a load — a maintenance
command that could would be the shortest path around every check in this
subsystem.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

__all__ = ["ModelCommandError", "add_arguments", "dispatch"]


class ModelCommandError(RuntimeError):
    """A model command could not be carried out."""


def _registry(arguments: argparse.Namespace) -> Any:
    """Build a registry from the arguments, importing the runtime lazily.

    Lazy because ``bunny-os`` runs on machines where the companion package may
    not be importable, and ``bunny-os status`` should not fail because of it.
    """
    try:
        from companion.models.registry import ModelRegistry
        from companion.models.events import ModelEventLog
    except ImportError as exc:  # pragma: no cover - depends on the install layout
        raise ModelCommandError(
            f"the companion runtime is not importable here: {exc}"
        ) from exc

    roots = [Path(item) for item in (arguments.root or [])] or None
    registry = ModelRegistry(
        roots=roots,
        state_root=Path(arguments.state) if arguments.state else None,
        backend=_backend(arguments),
    )
    registry.events = ModelEventLog(registry.events_path)
    return registry


def _backend(arguments: argparse.Namespace) -> Any:
    """The inference backend, or the honest null one.

    A machine with no model server gets :class:`NullAdapterBackend`, which
    lists and validates and activates nothing. That is the correct behaviour for
    a Bunny image as it ships, because no image ships an inference runtime.
    """
    endpoint = getattr(arguments, "llama_server", "")
    if not endpoint:
        from companion.models.inference import NullAdapterBackend

        return NullAdapterBackend()
    from companion.agents.wire import HttpTarget
    from companion.models.llama_server import LlamaServerAdapterBackend

    host, _, port = endpoint.partition(":")
    try:
        target = HttpTarget(scheme="http", host=host or "127.0.0.1", port=int(port or 8080))
    except Exception as exc:  # noqa: BLE001 - HttpTarget raises its own schema error
        raise ModelCommandError(f"{endpoint!r} is not a usable loopback endpoint: {exc}") from exc
    return LlamaServerAdapterBackend(target)


def _list(arguments: argparse.Namespace) -> dict[str, Any]:
    registry = _registry(arguments)
    models = registry.discover(verify_digest=not arguments.fast)
    active = registry.active()
    return {
        "roots": [str(item) for item in registry.roots],
        "backend": registry.backend.describe().to_json(),
        "models": [model.to_json() for model in models],
        "active": active.to_json(),
    }


def _validate(arguments: argparse.Namespace) -> dict[str, Any]:
    from companion.models.validation import validate_artifact

    registry = _registry(arguments)
    report = validate_artifact(
        Path(arguments.artifact),
        expectations=registry.expectations(verify_base=True),
        verify_digest=True,
    )
    return report.to_json()


def _inspect(arguments: argparse.Namespace) -> dict[str, Any]:
    registry = _registry(arguments)
    registry.discover()
    return registry.provenance(arguments.model_id)


def _enable(arguments: argparse.Namespace) -> dict[str, Any]:
    registry = _registry(arguments)
    registry.discover()
    decision = registry.enable(arguments.model_id)
    return {"decision": decision.to_json(), "provenance": registry.provenance(arguments.model_id)}


def _disable(arguments: argparse.Namespace) -> dict[str, Any]:
    registry = _registry(arguments)
    registry.discover()
    return {"decision": registry.disable(arguments.model_id or "").to_json()}


def _events(arguments: argparse.Namespace) -> dict[str, Any]:
    registry = _registry(arguments)
    return {
        "path": str(registry.events_path),
        "events": [event.to_json() for event in registry.events.read()][-int(arguments.limit):],
    }


_HANDLERS = {
    "list": _list,
    "validate": _validate,
    "inspect": _inspect,
    "enable": _enable,
    "disable": _disable,
    "events": _events,
}


def add_arguments(subparsers: Any) -> None:
    """Attach the ``model`` command group to the bunny-os CLI."""
    group = subparsers.add_parser("model", help="runtime model adapters: list, validate, enable")
    commands = group.add_subparsers(dest="model_command", required=True)

    def common(parser: argparse.ArgumentParser) -> argparse.ArgumentParser:
        parser.add_argument(
            "--root", action="append", metavar="DIR",
            help="an artifact directory to search (default: the trusted model directories)",
        )
        parser.add_argument("--state", metavar="DIR", help="where the registry keeps its state")
        parser.add_argument(
            "--llama-server", metavar="HOST:PORT",
            help="a loopback llama-server to apply adapters through; without it no "
                 "backend is available and nothing can be activated",
        )
        return parser

    listing = common(commands.add_parser("list", help="every artifact and its validation status"))
    listing.add_argument(
        "--fast", action="store_true",
        help="skip adapter digests for the listing only; enabling always verifies them",
    )

    validate = common(commands.add_parser("validate", help="validate an artifact directory"))
    validate.add_argument("artifact", help="the artifact directory")

    inspect = common(commands.add_parser("inspect", help="provenance for one model"))
    inspect.add_argument("model_id")

    enable = common(commands.add_parser("enable", help="validate, apply and verify one model"))
    enable.add_argument("model_id")

    disable = common(commands.add_parser("disable", help="release the adapter and fall back"))
    disable.add_argument("model_id", nargs="?", default="")

    events = common(commands.add_parser("events", help="the model bridge's structured events"))
    events.add_argument("--limit", type=int, default=50)


def dispatch(arguments: argparse.Namespace) -> Any:
    handler = _HANDLERS.get(getattr(arguments, "model_command", ""))
    if handler is None:  # pragma: no cover - argparse requires the subcommand
        raise ModelCommandError(f"unknown model command {arguments.model_command!r}")
    return handler(arguments)
