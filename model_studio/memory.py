# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""How much memory a run needs, derived — and ``None`` when it cannot be.

Every number this module produces comes out of arithmetic on the model's own
configuration and the run's own parameters. There is no lookup table of "a 7B
model needs 16 GB", no fudge factor, and no default that stands in for a
measurement. When an input is missing, the result is ``None`` all the way up to
the report, which prints ``UNKNOWN``.

The model, stated so it can be argued with:

``base weights``
    ``parameters x bytes(dtype)``. Frozen under LoRA, so they carry no gradient
    and no optimizer state — which is the entire reason LoRA fits where full
    fine-tuning does not.
``adapters``
    for each adapted linear layer, ``rank x (in_features + out_features)``. Not
    a fraction of the base: an exact count over the layers the plan will
    actually wrap.
``gradients``
    one per trainable parameter, in the training dtype.
``optimizer``
    AdamW keeps two float32 moments per trainable parameter. Eight bytes each,
    regardless of the training dtype, because the moments are not cast.
``activations``
    with gradient checkpointing, one hidden state per layer boundary plus the
    working set of the single block being recomputed. Without it, every block's
    saved tensors at once.

Two things it deliberately excludes, and says so rather than absorbing into a
constant: the allocator's fragmentation, and the framework's own footprint
(CUDA context, kernels, the interpreter). Both are real and neither is derivable
from the configuration. That is why :class:`MemoryEstimate` is compared against
a *measured* peak after every run — the estimate is a planning tool, and the
measurement is the evidence.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from .models import ModelArchitecture

__all__ = [
    "DTYPE_BYTES",
    "MemoryEstimate",
    "adapter_parameters",
    "estimate_training_memory",
    "resolve_batch_size",
]

#: Bytes per stored parameter. The 4-bit figure is the NF4 payload; its
#: per-block scales and the double-quantized constants add roughly a further
#: 3% and are counted in the ``quantizationConstants`` component rather than
#: hidden inside this number.
DTYPE_BYTES: Mapping[str, float] = {
    "fp32": 4.0,
    "bf16": 2.0,
    "fp16": 2.0,
    "int8": 1.0,
    "nf4": 0.5,
}

#: Saved-tensor counts per token for one gated-MLP decoder block, in units of
#: ``hidden`` and ``intermediate``. Derived by counting what a standard block
#: keeps for its backward pass: the block input, the normalized input, the
#: attention output, the residual, the post-attention norm, the attention
#: projection input (hidden-sized, six of them), and the gate, up and activation
#: products (intermediate-sized, three of them).
_SAVED_HIDDEN_PER_BLOCK = 6
_SAVED_INTERMEDIATE_PER_BLOCK = 3

#: With checkpointing, only the block *boundary* is kept, and the recompute
#: working set is one block's worth of the same tensors.
_CHECKPOINT_BOUNDARY_HIDDEN = 1


@dataclass(frozen=True)
class MemoryEstimate:
    """A derived requirement, with its parts and its exclusions visible."""

    components: dict[str, int] = field(default_factory=dict)
    formula: str = ""
    excludes: tuple[str, ...] = ()

    @property
    def total_bytes(self) -> int:
        return sum(self.components.values())

    def to_json(self) -> dict[str, Any]:
        return {
            "totalBytes": self.total_bytes,
            "components": dict(self.components),
            "formula": self.formula,
            "excludes": list(self.excludes),
        }


#: The linear layers a LoRA plan may adapt, and their shapes in terms of the
#: architecture. ``attention`` is the default set.
def _layer_shapes(architecture: ModelArchitecture) -> dict[str, tuple[int, int]]:
    hidden = architecture.hidden_size
    projected = architecture.attention_heads * architecture.head_dimension
    key_value = architecture.key_value_heads * architecture.head_dimension
    intermediate = architecture.intermediate_size
    return {
        "q_proj": (hidden, projected),
        "k_proj": (hidden, key_value),
        "v_proj": (hidden, key_value),
        "o_proj": (projected, hidden),
        "gate_proj": (hidden, intermediate),
        "up_proj": (hidden, intermediate),
        "down_proj": (intermediate, hidden),
    }


def adapter_parameters(
    architecture: ModelArchitecture, *, rank: int, target_modules: Sequence[str]
) -> int | None:
    """Trainable parameters a LoRA plan adds. ``None`` if a target is unrecognised.

    ``rank x (in + out)`` per adapted layer, summed over layers — the exact
    count, because it is exactly countable. A target this build does not know
    the shape of makes the whole figure ``None`` rather than a total that is
    quietly missing a term.
    """
    shapes = _layer_shapes(architecture)
    total = 0
    for name in target_modules:
        shape = shapes.get(name)
        if shape is None:
            return None
        inputs, outputs = shape
        total += rank * (inputs + outputs)
    return total * architecture.layers


def estimate_training_memory(
    architecture: ModelArchitecture | None,
    *,
    dtype: str,
    base_dtype: str,
    batch_size: int,
    sequence_length: int,
    rank: int,
    target_modules: Sequence[str],
    gradient_checkpointing: bool,
    quantization_bits: int = 0,
) -> MemoryEstimate | None:
    """The derived requirement, or ``None`` when the architecture is not known."""
    if architecture is None:
        return None
    trainable = adapter_parameters(architecture, rank=rank, target_modules=target_modules)
    if trainable is None:
        return None

    weight_bytes = DTYPE_BYTES.get(base_dtype)
    train_bytes = DTYPE_BYTES.get(dtype)
    if weight_bytes is None or train_bytes is None:
        return None

    parameters = architecture.parameter_count
    components: dict[str, int] = {
        "baseWeights": int(parameters * weight_bytes),
        "adapters": int(trainable * train_bytes),
        "gradients": int(trainable * train_bytes),
        # AdamW: exp_avg and exp_avg_sq, both float32.
        "optimizer": int(trainable * 8),
    }
    if quantization_bits:
        # NF4/INT8 keep a scale per block (64 weights) and, with double
        # quantization, a quantized scale for each group of scales. Counted, not
        # folded into the bytes-per-parameter figure, so it can be checked.
        components["quantizationConstants"] = int(parameters / 64 * 4 + parameters / 64 / 256 * 4)

    tokens = batch_size * sequence_length
    hidden = architecture.hidden_size
    intermediate = architecture.intermediate_size
    layers = architecture.layers
    activation_bytes = train_bytes

    if gradient_checkpointing:
        boundary = layers * tokens * hidden * _CHECKPOINT_BOUNDARY_HIDDEN
        recompute = tokens * (
            _SAVED_HIDDEN_PER_BLOCK * hidden + _SAVED_INTERMEDIATE_PER_BLOCK * intermediate
        )
        components["activations"] = int((boundary + recompute) * activation_bytes)
        activation_note = (
            "activations = (layers x batch x seq x hidden + batch x seq x "
            f"({_SAVED_HIDDEN_PER_BLOCK} x hidden + {_SAVED_INTERMEDIATE_PER_BLOCK} x "
            "intermediate)) x bytes  [gradient checkpointing: boundaries plus one "
            "recomputed block]"
        )
    else:
        per_layer = tokens * (
            _SAVED_HIDDEN_PER_BLOCK * hidden + _SAVED_INTERMEDIATE_PER_BLOCK * intermediate
        )
        components["activations"] = int(layers * per_layer * activation_bytes)
        activation_note = (
            f"activations = layers x batch x seq x ({_SAVED_HIDDEN_PER_BLOCK} x hidden + "
            f"{_SAVED_INTERMEDIATE_PER_BLOCK} x intermediate) x bytes  [no checkpointing]"
        )

    # The output projection over the vocabulary, and its float32 logits. At a
    # 49k vocabulary and 512 tokens this is not a rounding error, and leaving it
    # out is how an estimate comes in 20% under on a small model.
    components["logits"] = int(tokens * architecture.vocabulary * 4 * 2)

    return MemoryEstimate(
        components=components,
        formula=(
            "baseWeights = parameters x bytes(base dtype); "
            "adapters = gradients = rank x sum(in+out) x layers x bytes(dtype); "
            "optimizer = 8 bytes x trainable [AdamW, two float32 moments]; "
            f"{activation_note}; "
            "logits = batch x seq x vocabulary x 4 x 2 [float32 logits and their gradient]"
        ),
        excludes=(
            "allocator fragmentation",
            "the CUDA context and kernel images",
            "the Python interpreter and framework footprint",
            "the full attention matrix, which memory-efficient attention does not materialise",
        ),
    )


def resolve_batch_size(
    requested: int | str,
    *,
    available_bytes: int | None,
    estimate_for: Any,
    ceiling: int = 8,
) -> tuple[int, str]:
    """Turn ``batch_size: auto`` into a number, with the reason it chose that number.

    ``estimate_for`` is a callable taking a batch size and returning a
    :class:`MemoryEstimate` or ``None``. The search is a plain upward scan to
    ``ceiling`` against a *fraction* of measured free memory — nothing adaptive,
    nothing that retries after an out-of-memory error, because a plan that only
    becomes known after it has crashed once is not a plan.

    Unmeasurable memory resolves to 1. That is the conservative answer and it is
    stated as such, rather than being a default that looks like a decision.
    """
    if isinstance(requested, int):
        return requested, f"batch size {requested} was given in the configuration"
    if available_bytes is None:
        return 1, "free memory could not be measured; batch size 1 is the conservative choice"

    # Two thirds: the estimate excludes fragmentation and the framework's own
    # footprint, and this is the headroom left for them. Stated here rather than
    # folded into the estimate, so the estimate stays a statement about the model.
    budget = int(available_bytes * 2 / 3)
    chosen = 1
    for candidate in range(1, ceiling + 1):
        estimate = estimate_for(candidate)
        if estimate is None:
            return 1, "the memory requirement could not be derived; batch size 1 is the conservative choice"
        if estimate.total_bytes > budget:
            break
        chosen = candidate
    return chosen, (
        f"batch size {chosen} is the largest whose derived requirement fits two thirds of "
        f"the {available_bytes / (1024 ** 3):.1f} GiB measured free"
    )
