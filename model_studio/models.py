# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Finding the base model, and refusing to fetch one nobody approved.

Resolution has three outcomes and they are kept distinct, because collapsing
them is how a subsystem acquires a silent download:

``local``
    ``model.base`` names a directory that exists. Nothing is fetched, ever.
``cached``
    it names a Hugging Face repository whose snapshot is already in the local
    hub cache. Nothing is fetched either — the bytes are here, and the exact
    revision they came from is read back out of the cache rather than assumed.
``absent``
    it is neither. This is the only case that can involve the network, and it
    does not proceed without :class:`~model_studio.network.NetworkPolicy`
    saying so for this invocation.

The architecture reader is here for a reason that is not obvious: it is what
makes an *honest* VRAM estimate possible. A number like "estimated VRAM 2.1 GB"
either comes from the model's real parameter count or it comes from nowhere.
:func:`read_architecture` computes the count from ``config.json`` — the same
arithmetic the model itself implies — and returns ``None`` when the file
describes an architecture it does not recognise, so the estimate becomes
``UNKNOWN`` rather than a plausible-looking fiction.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
from typing import Any

from .errors import ConfigurationError
from .network import NetworkPolicy

__all__ = [
    "ModelArchitecture",
    "ResolvedModel",
    "hub_cache_root",
    "read_architecture",
    "resolve_base_model",
]


@dataclass(frozen=True)
class ModelArchitecture:
    """The shape of a decoder model, read from its own configuration."""

    model_type: str
    hidden_size: int
    layers: int
    attention_heads: int
    key_value_heads: int
    intermediate_size: int
    vocabulary: int
    head_dimension: int
    tied_embeddings: bool
    max_position_embeddings: int = 0

    @property
    def parameter_count(self) -> int:
        """Parameters implied by this configuration, counted rather than looked up.

        A gated-MLP decoder (Llama, Qwen, SmolLM and everything shaped like
        them): embeddings, then per layer four attention projections and three
        MLP projections and two RMS norms, then a final norm and — only when the
        embeddings are not tied — a separate output projection.

        This is checked against a real model in the tests: SmolLM2-135M's own
        ``config.json`` must come out at 134.5M, because a memory estimate built
        on a parameter count that is wrong by a factor is worse than no estimate.
        """
        embedding = self.vocabulary * self.hidden_size
        attention = (
            self.hidden_size * self.attention_heads * self.head_dimension  # q
            + 2 * self.hidden_size * self.key_value_heads * self.head_dimension  # k, v
            + self.attention_heads * self.head_dimension * self.hidden_size  # o
        )
        mlp = 3 * self.hidden_size * self.intermediate_size
        norms = 2 * self.hidden_size
        per_layer = attention + mlp + norms
        total = embedding + self.layers * per_layer + self.hidden_size
        if not self.tied_embeddings:
            total += self.vocabulary * self.hidden_size
        return total

    def to_json(self) -> dict[str, Any]:
        return {
            "modelType": self.model_type,
            "hiddenSize": self.hidden_size,
            "layers": self.layers,
            "attentionHeads": self.attention_heads,
            "keyValueHeads": self.key_value_heads,
            "intermediateSize": self.intermediate_size,
            "vocabulary": self.vocabulary,
            "headDimension": self.head_dimension,
            "tiedEmbeddings": self.tied_embeddings,
            "parameterCount": self.parameter_count,
        }


#: Architectures whose parameter count the arithmetic above is correct for. A
#: model outside this list is not refused — it is simply not *estimated*, and
#: the plan says ``UNKNOWN`` where a number would have gone.
_GATED_DECODERS = frozenset({
    "llama", "mistral", "qwen2", "qwen3", "smollm", "smollm3", "gemma", "gemma2",
    "phi3", "olmo", "olmo2", "starcoder2", "granite",
})


def read_architecture(directory: Path | str) -> ModelArchitecture | None:
    """Read ``config.json``. ``None`` means "this cannot be estimated", not "small"."""
    path = Path(directory) / "config.json"
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(document, dict):
        return None
    # transformers v5 nests the decoder configuration for multimodal models.
    text = document.get("text_config")
    if isinstance(text, dict):
        document = {**document, **text}

    model_type = str(document.get("model_type", "")).lower()
    if model_type not in _GATED_DECODERS:
        return None

    try:
        hidden = int(document["hidden_size"])
        layers = int(document["num_hidden_layers"])
        heads = int(document["num_attention_heads"])
        intermediate = int(document["intermediate_size"])
        vocabulary = int(document["vocab_size"])
    except (KeyError, TypeError, ValueError):
        return None

    key_value = document.get("num_key_value_heads", heads)
    try:
        key_value = int(key_value)
    except (TypeError, ValueError):
        key_value = heads
    head_dimension = document.get("head_dim") or (hidden // heads if heads else 0)
    try:
        head_dimension = int(head_dimension)
    except (TypeError, ValueError):
        return None
    if min(hidden, layers, heads, intermediate, vocabulary, head_dimension) <= 0:
        return None

    return ModelArchitecture(
        model_type=model_type,
        hidden_size=hidden,
        layers=layers,
        attention_heads=heads,
        key_value_heads=key_value,
        intermediate_size=intermediate,
        vocabulary=vocabulary,
        head_dimension=head_dimension,
        tied_embeddings=bool(document.get("tie_word_embeddings", False)),
        max_position_embeddings=int(document.get("max_position_embeddings", 0) or 0),
    )


@dataclass(frozen=True)
class ResolvedModel:
    """Where the base model is, or precisely why it is not here."""

    reference: str
    requested_revision: str
    state: str  # local | cached | absent
    path: str = ""
    resolved_revision: str = ""
    architecture: ModelArchitecture | None = None
    detail: str = ""

    @property
    def present(self) -> bool:
        return self.state in ("local", "cached")

    def to_json(self) -> dict[str, Any]:
        return {
            "reference": self.reference,
            "requestedRevision": self.requested_revision,
            "state": self.state,
            "path": self.path,
            "resolvedRevision": self.resolved_revision,
            "architecture": self.architecture.to_json() if self.architecture else None,
            "detail": self.detail,
        }


def hub_cache_root() -> Path:
    """The Hugging Face hub cache, honouring the same variables the library does."""
    for name in ("HF_HUB_CACHE", "HUGGINGFACE_HUB_CACHE"):
        value = os.environ.get(name, "").strip()
        if value:
            return Path(value)
    home = os.environ.get("HF_HOME", "").strip()
    if home:
        return Path(home) / "hub"
    return Path.home() / ".cache" / "huggingface" / "hub"


def _cached_snapshot(reference: str, revision: str) -> tuple[Path | None, str]:
    """The snapshot directory for ``reference@revision`` if it is already here.

    Reads the cache's own ``refs`` file rather than guessing a directory name,
    and returns the *commit* the reference resolved to — so a run pinned to
    ``main`` records the forty characters that ``main`` actually meant on the
    day it ran, which is the difference between provenance and a note.
    """
    root = hub_cache_root()
    folder = root / ("models--" + reference.replace("/", "--"))
    if not folder.is_dir():
        return None, ""

    snapshots = folder / "snapshots"
    direct = snapshots / revision
    if direct.is_dir():
        return direct, revision

    reference_file = folder / "refs" / revision
    try:
        commit = reference_file.read_text(encoding="utf-8").strip()
    except OSError:
        commit = ""
    if commit and (snapshots / commit).is_dir():
        return snapshots / commit, commit

    # A cache populated by an older client, or a revision fetched by digest.
    if snapshots.is_dir():
        candidates = sorted(item for item in snapshots.iterdir() if item.is_dir())
        if len(candidates) == 1 and revision in ("main", ""):
            return candidates[0], candidates[0].name
    return None, ""


def resolve_base_model(
    reference: str,
    *,
    revision: str = "main",
    policy: NetworkPolicy | None = None,
    download: bool = False,
) -> ResolvedModel:
    """Locate the base model. Never reaches the network unless ``download`` is asked for.

    ``download`` is separate from ``policy`` because they answer different
    questions: the policy is whether this invocation *may* fetch, and the flag
    is whether this call is the one doing it. Preflight resolves with
    ``download=False`` on every run, so a preflight is always offline even when
    the invocation has an approval in hand.
    """
    if not reference.strip():
        raise ConfigurationError("model.base is empty")

    candidate = Path(reference).expanduser()
    if candidate.is_dir():
        architecture = read_architecture(candidate)
        return ResolvedModel(
            reference=reference,
            requested_revision=revision,
            state="local",
            path=str(candidate.resolve()),
            resolved_revision="local-directory",
            architecture=architecture,
            detail=(
                "a local directory; nothing was fetched"
                if architecture
                else "a local directory whose config.json is missing or describes an "
                     "architecture this build cannot size"
            ),
        )

    if "/" not in reference or reference.count("/") > 1:
        return ResolvedModel(
            reference=reference,
            requested_revision=revision,
            state="absent",
            detail=(
                f"{reference!r} is neither an existing directory nor an 'organisation/name' "
                "repository identifier"
            ),
        )

    snapshot, commit = _cached_snapshot(reference, revision)
    if snapshot is not None:
        return ResolvedModel(
            reference=reference,
            requested_revision=revision,
            state="cached",
            path=str(snapshot),
            resolved_revision=commit,
            architecture=read_architecture(snapshot),
            detail=f"already in the local hub cache at {hub_cache_root()}",
        )

    if not download:
        return ResolvedModel(
            reference=reference,
            requested_revision=revision,
            state="absent",
            detail=(
                f"{reference}@{revision} is not in the local hub cache "
                f"({hub_cache_root()}) and this operation does not download"
            ),
        )

    active = policy or NetworkPolicy()
    active.require_download(f"the base model {reference}@{revision}")
    return _download(reference, revision, active)


def _download(reference: str, revision: str, policy: NetworkPolicy) -> ResolvedModel:
    """Fetch an approved base model. The only network call in this package."""
    from . import network  # local import: keeps the module graph honest for the grep test

    try:
        from huggingface_hub import snapshot_download  # type: ignore
    except ImportError as exc:
        raise ConfigurationError(
            "downloading a base model needs huggingface_hub, which is not installed. "
            "Install it, or point model.base at a local directory."
        ) from exc

    with network.applied(policy):
        try:
            location = snapshot_download(
                repo_id=reference,
                revision=revision,
                # Weights, tokenizer and configuration. Not the whole repository:
                # model repositories carry demo notebooks, images and sometimes
                # arbitrary scripts, and none of that belongs on a machine that
                # asked for a base model.
                allow_patterns=[
                    "*.json", "*.safetensors", "*.model", "*.txt", "tokenizer*", "*.jinja",
                ],
            )
        except Exception as exc:  # noqa: BLE001 - hub raises a family of its own types
            raise ConfigurationError(
                f"could not fetch {reference}@{revision}: {type(exc).__name__}: {exc}"
            ) from exc

    path = Path(location)
    _, commit = _cached_snapshot(reference, revision)
    return ResolvedModel(
        reference=reference,
        requested_revision=revision,
        state="cached",
        path=str(path),
        resolved_revision=commit or path.name,
        architecture=read_architecture(path),
        detail=f"downloaded with explicit approval: {policy.reason or 'approved at the command line'}",
    )
