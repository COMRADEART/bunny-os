# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""One training run, declared in a document, checked before anything runs.

The whole point of a declarative configuration is that the expensive, slow,
partly-irreversible thing downstream of it can be refused *cheaply*. So this
module is strict in three ways that a permissive loader would not be:

**Unknown keys are errors.** ``lr: 0.0002`` is not a learning rate; it is a
typo, and a loader that ignores it trains at the default and reports success.
The two runs are indistinguishable from their logs and produce different models.
Every section is closed, and the error names the key and the section.

**Contradictions are errors, not reconciliations.** ``method: lora`` with
``quantization.enabled: true`` is two statements about the same run that cannot
both hold. Picking one — either one — means the document and the run disagree,
and the provenance record would then describe a run that did not happen. The
rule is stated once, in :func:`_check_combinations`, and it refuses.

**There is no network in this document.** No ``push_to_hub``, no
``upload``, no ``dataset: org/name`` that resolves over HTTP, and no
``trust_remote_code: true``. A configuration file is a thing people copy from
the internet and run; it is the wrong place to be able to grant network access
or arbitrary code execution. Network approval is a command-line act, made by the
person at the keyboard, for one invocation — see :mod:`model_studio.network`.

Two digests come out of loading, and they answer different questions.
``file_sha256`` is over the bytes on disk: it answers "was this the document?".
``canonical_sha256`` is over the resolved values in sorted JSON: it answers "was
this the *run*?", and is stable across reformatting, key order and comments.
Provenance records both.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping, Sequence

from .errors import ConfigurationError

__all__ = [
    "CONFIG_SCHEMA_PATH",
    "CONFIG_VERSION",
    "DatasetConfig",
    "LoraConfig",
    "ModelConfig",
    "OutputConfig",
    "QuantizationConfig",
    "TrainingConfig",
    "TrainingParameters",
    "load_config",
    "load_document",
    "parse_simple_yaml",
]

CONFIG_VERSION = 1
CONFIG_SCHEMA_PATH = Path(__file__).with_name("schemas") / "bunny-training-config.schema.json"

#: A configuration document is small. A file larger than this is either not a
#: configuration or is trying to be a payload, and either way it is refused
#: before a parser sees it.
_MAX_DOCUMENT_BYTES = 256 * 1024


# --------------------------------------------------------------------------- #
# Loading: YAML when PyYAML is here, a strict subset when it is not
# --------------------------------------------------------------------------- #

_SCALAR_INT = re.compile(r"^[+-]?\d+$")
_SCALAR_FLOAT = re.compile(r"^[+-]?(\d+\.\d*|\.\d+|\d+)([eE][+-]?\d+)?$")


def _scalar(token: str, line_number: int) -> Any:
    text = token.strip()
    if not text:
        return ""
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'":
        return text[1:-1]
    lowered = text.lower()
    if lowered in ("true", "yes", "on"):
        return True
    if lowered in ("false", "no", "off"):
        return False
    if lowered in ("null", "~"):
        return None
    if _SCALAR_INT.match(text):
        return int(text)
    if _SCALAR_FLOAT.match(text):
        return float(text)
    if text.startswith("[") and text.endswith("]"):
        inner = text[1:-1].strip()
        if not inner:
            return []
        return [_scalar(part, line_number) for part in inner.split(",")]
    if text.startswith(("{", "&", "*", "!", "|", ">")):
        raise ConfigurationError(
            f"line {line_number}: {text[0]!r} needs a full YAML parser; install PyYAML "
            "or write this document as JSON"
        )
    return text


def _strip_comment(line: str) -> str:
    """Remove a trailing comment, leaving ``#`` inside a quoted scalar alone."""
    quote = ""
    for index, character in enumerate(line):
        if quote:
            if character == quote:
                quote = ""
        elif character in "\"'":
            quote = character
        elif character == "#" and (index == 0 or line[index - 1] in " \t"):
            return line[:index]
    return line


@dataclass(frozen=True)
class _Line:
    number: int
    indent: int
    body: str


def _significant_lines(text: str) -> list[_Line]:
    lines: list[_Line] = []
    for number, raw in enumerate(text.splitlines(), start=1):
        stripped = _strip_comment(raw).rstrip()
        if not stripped.strip() or stripped.lstrip().startswith("---"):
            continue
        leading = stripped[: len(stripped) - len(stripped.lstrip())]
        if "\t" in leading:
            raise ConfigurationError(f"line {number}: tabs are not valid YAML indentation")
        indent = len(leading)
        lines.append(_Line(number, indent, stripped.strip()))
    return lines


def _parse_block(lines: list[_Line], start: int, indent: int) -> tuple[Any, int]:
    """One block at ``indent``, decided by its first line rather than guessed.

    Whether a key opens a mapping or a sequence is visible from the line after
    it, so this looks, instead of building both shapes and settling later. The
    return is the value and the index of the first line that is not part of it.
    """
    if start >= len(lines):
        return None, start

    if lines[start].body.startswith("- "):
        sequence: list[Any] = []
        index = start
        while index < len(lines) and lines[index].indent == indent:
            line = lines[index]
            if not line.body.startswith("- "):
                break
            sequence.append(_scalar(line.body[2:], line.number))
            index += 1
        return sequence, index

    mapping: dict[str, Any] = {}
    index = start
    while index < len(lines) and lines[index].indent == indent:
        line = lines[index]
        if line.body.startswith("- "):
            raise ConfigurationError(
                f"line {line.number}: a sequence entry inside a mapping at the same indentation"
            )
        if ":" not in line.body:
            raise ConfigurationError(
                f"line {line.number}: {line.body!r} is neither a mapping entry nor a sequence entry"
            )
        key, _, remainder = line.body.partition(":")
        key = key.strip()
        if not key:
            raise ConfigurationError(f"line {line.number}: empty key")
        if key in mapping:
            raise ConfigurationError(f"line {line.number}: duplicate key {key!r}")
        remainder = remainder.strip()
        index += 1
        if remainder:
            mapping[key] = _scalar(remainder, line.number)
            continue
        if index < len(lines) and lines[index].indent > indent:
            mapping[key], index = _parse_block(lines, index, lines[index].indent)
        else:
            mapping[key] = None
    return mapping, index


def parse_simple_yaml(text: str) -> dict[str, Any]:
    """The subset of YAML a Bunny training document uses, parsed strictly.

    Nested mappings, block sequences of scalars, inline ``[a, b]`` sequences,
    comments, and the scalar types. Anything else raises rather than being
    approximated: a configuration parser that half-understands a document is
    worse than one that refuses it, because the half it understood still runs.

    This exists because PyYAML is optional in this repository — the workflow
    validator skips when it is absent — and a training configuration that could
    only be read on machines with an optional dependency is not a configuration
    format, it is a dependency. :mod:`tests.model_studio.test_config` parses the
    same documents both ways wherever PyYAML is installed and requires the
    results to be equal, so the subset cannot drift into its own dialect.
    """
    lines = _significant_lines(text)
    if not lines:
        return {}
    if lines[0].indent != 0:
        raise ConfigurationError(f"line {lines[0].number}: the document starts indented")
    document, index = _parse_block(lines, 0, 0)
    if index != len(lines):
        raise ConfigurationError(
            f"line {lines[index].number}: indentation does not line up with any parent"
        )
    if document is None:
        return {}
    if not isinstance(document, dict):
        raise ConfigurationError("the top level of a training configuration is a mapping")
    return document


def load_document(path: Path | str) -> tuple[dict[str, Any], bytes, str]:
    """Read a configuration document. Returns the mapping, its bytes, and the loader.

    The loader name is returned rather than hidden because it goes into
    provenance: "PyYAML 6.0.3" and "bunny subset parser" are different readings
    of the same file in principle, and a record that says which one ran is a
    record someone can reproduce.
    """
    file = Path(path)
    try:
        data = file.read_bytes()
    except OSError as exc:
        raise ConfigurationError(f"cannot read {file}: {exc}") from exc
    if len(data) > _MAX_DOCUMENT_BYTES:
        raise ConfigurationError(
            f"{file} is {len(data)} bytes; a training configuration is at most {_MAX_DOCUMENT_BYTES}"
        )
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ConfigurationError(f"{file} is not UTF-8: {exc}") from exc

    if file.suffix.lower() == ".json":
        try:
            document = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ConfigurationError(f"{file} is not valid JSON: {exc}") from exc
        loader = "json"
    else:
        try:
            import yaml  # type: ignore
        except ImportError:
            document = parse_simple_yaml(text)
            loader = "bunny-subset-yaml"
        else:
            try:
                document = yaml.safe_load(text)
            except yaml.YAMLError as exc:
                raise ConfigurationError(f"{file} is not valid YAML: {exc}") from exc
            loader = f"pyyaml-{getattr(yaml, '__version__', '?')}"

    if document is None:
        document = {}
    if not isinstance(document, dict):
        raise ConfigurationError(f"{file}: the top level of a training configuration is a mapping")
    return document, data, loader


# --------------------------------------------------------------------------- #
# The resolved configuration
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class ModelConfig:
    base: str
    revision: str = "main"
    trust_remote_code: bool = False


@dataclass(frozen=True)
class TrainingParameters:
    method: str = "lora"
    epochs: int = 1
    batch_size: int | str = "auto"
    gradient_accumulation_steps: int = 1
    learning_rate: float = 2e-4
    max_length: int = 512
    gradient_checkpointing: bool = True
    precision: str = "auto"
    seed: int = 0
    max_steps: int = 0
    warmup_steps: int = 0


@dataclass(frozen=True)
class QuantizationConfig:
    enabled: bool = False
    bits: int = 4
    compute_dtype: str = "auto"
    double_quantization: bool = True


@dataclass(frozen=True)
class LoraConfig:
    rank: int = 16
    alpha: int = 32
    dropout: float = 0.05
    target_modules: tuple[str, ...] = ()
    bias: str = "none"


@dataclass(frozen=True)
class DatasetConfig:
    path: str = ""
    format: str = "chat"
    validation_split: float = 0.0
    max_examples: int = 0
    policy_check: bool = True


@dataclass(frozen=True)
class OutputConfig:
    directory: str = ""
    name: str = ""
    overwrite: bool = False


@dataclass(frozen=True)
class TrainingConfig:
    """A validated run. Constructing one is the guarantee that it is coherent."""

    model: ModelConfig
    training: TrainingParameters
    quantization: QuantizationConfig
    lora: LoraConfig
    dataset: DatasetConfig
    output: OutputConfig
    version: int = CONFIG_VERSION
    source_path: str = ""
    loader: str = ""
    file_sha256: str = ""
    base_directory: str = ""

    # -- derived paths ----------------------------------------------------- #

    @property
    def dataset_path(self) -> Path:
        return self._resolve(self.dataset.path)

    @property
    def output_directory(self) -> Path:
        return self._resolve(self.output.directory)

    @property
    def run_name(self) -> str:
        return self.output.name or self.output_directory.name

    def _resolve(self, value: str) -> Path:
        candidate = Path(value)
        if candidate.is_absolute():
            return candidate
        base = Path(self.base_directory) if self.base_directory else Path.cwd()
        return (base / candidate).resolve()

    # -- serialisation ------------------------------------------------------ #

    def to_json(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "model": asdict(self.model),
            "training": asdict(self.training),
            "quantization": asdict(self.quantization),
            "lora": {**asdict(self.lora), "target_modules": list(self.lora.target_modules)},
            "dataset": asdict(self.dataset),
            "output": asdict(self.output),
        }

    @property
    def canonical_sha256(self) -> str:
        """A digest of the run, not of the file that described it."""
        payload = json.dumps(self.to_json(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    @property
    def effective_method(self) -> str:
        return "qlora" if self.quantization.enabled else "lora"


# --------------------------------------------------------------------------- #
# Validation
# --------------------------------------------------------------------------- #

_SECTIONS: Mapping[str, tuple[str, ...]] = {
    "model": ("base", "revision", "trust_remote_code"),
    "training": (
        "method", "epochs", "batch_size", "gradient_accumulation_steps", "learning_rate",
        "max_length", "gradient_checkpointing", "precision", "seed", "max_steps", "warmup_steps",
    ),
    "quantization": ("enabled", "bits", "compute_dtype", "double_quantization"),
    "lora": ("rank", "alpha", "dropout", "target_modules", "bias"),
    "dataset": ("path", "format", "validation_split", "max_examples", "policy_check"),
    "output": ("directory", "name", "overwrite"),
}

_REQUIRED_SECTIONS = ("model", "training", "dataset", "output")


def _section(document: Mapping[str, Any], name: str) -> dict[str, Any]:
    value = document.get(name, {})
    if value is None:
        value = {}
    if not isinstance(value, Mapping):
        raise ConfigurationError(f"{name}: expected a mapping, found {type(value).__name__}")
    unknown = sorted(set(value) - set(_SECTIONS[name]))
    if unknown:
        raise ConfigurationError(
            f"{name}: unknown key(s) {', '.join(repr(item) for item in unknown)}; "
            f"this section accepts {', '.join(_SECTIONS[name])}"
        )
    return dict(value)


def _text(section: Mapping[str, Any], key: str, default: str, *, where: str) -> str:
    value = section.get(key, default)
    if not isinstance(value, str):
        raise ConfigurationError(f"{where}.{key}: expected a string, found {type(value).__name__}")
    return value


def _integer(section: Mapping[str, Any], key: str, default: int, *, where: str,
             minimum: int, maximum: int) -> int:
    value = section.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigurationError(f"{where}.{key}: expected an integer, found {value!r}")
    if not minimum <= value <= maximum:
        raise ConfigurationError(f"{where}.{key}: {value} is outside {minimum}..{maximum}")
    return value


def _number(section: Mapping[str, Any], key: str, default: float, *, where: str,
            minimum: float, maximum: float, exclusive_minimum: bool = False) -> float:
    value = section.get(key, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigurationError(f"{where}.{key}: expected a number, found {value!r}")
    value = float(value)
    if exclusive_minimum and value <= minimum:
        raise ConfigurationError(f"{where}.{key}: {value} must be greater than {minimum}")
    if not exclusive_minimum and value < minimum:
        raise ConfigurationError(f"{where}.{key}: {value} is below {minimum}")
    if value > maximum:
        raise ConfigurationError(f"{where}.{key}: {value} is above {maximum}")
    return value


def _flag(section: Mapping[str, Any], key: str, default: bool, *, where: str) -> bool:
    value = section.get(key, default)
    if not isinstance(value, bool):
        raise ConfigurationError(f"{where}.{key}: expected true or false, found {value!r}")
    return value


def _choice(section: Mapping[str, Any], key: str, default: str, *, where: str,
            allowed: Sequence[str]) -> str:
    value = _text(section, key, default, where=where)
    if value not in allowed:
        raise ConfigurationError(
            f"{where}.{key}: {value!r} is not one of {', '.join(allowed)}"
        )
    return value


def _check_combinations(
    training: TrainingParameters,
    quantization: QuantizationConfig,
    lora: LoraConfig,
    dataset: DatasetConfig,
) -> None:
    """The rules that are about two fields at once. Each one refuses; none reconciles."""
    if training.method == "qlora" and not quantization.enabled:
        raise ConfigurationError(
            "training.method is 'qlora' but quantization.enabled is false. QLoRA *is* "
            "LoRA over a quantized base; enable quantization or use method 'lora'."
        )
    if training.method == "lora" and quantization.enabled:
        raise ConfigurationError(
            "training.method is 'lora' but quantization.enabled is true. A quantized "
            "base with LoRA adapters is QLoRA; say so, so the record matches the run."
        )
    if quantization.enabled and quantization.bits not in (4, 8):
        raise ConfigurationError(f"quantization.bits: {quantization.bits} is not 4 or 8")
    if lora.alpha < lora.rank:
        # Not an error in the mathematics, but almost always a transposition of
        # the two, and the scaling it produces (alpha/rank < 1) shrinks the
        # update instead of amplifying it. Warned about by refusing, because a
        # run that quietly learns nothing is the expensive failure here.
        raise ConfigurationError(
            f"lora.alpha ({lora.alpha}) is below lora.rank ({lora.rank}); the LoRA scaling "
            "alpha/rank would be under 1, which shrinks every update. Alpha is "
            "conventionally the rank or twice it."
        )
    if training.max_steps and training.warmup_steps >= training.max_steps:
        raise ConfigurationError(
            f"training.warmup_steps ({training.warmup_steps}) is not below training.max_steps "
            f"({training.max_steps}); the run would end while still warming up"
        )
    if dataset.validation_split and dataset.max_examples and dataset.max_examples < 2:
        raise ConfigurationError(
            "dataset.validation_split needs at least two examples to split"
        )


def config_from_mapping(
    document: Mapping[str, Any],
    *,
    base_directory: Path | str = "",
    source_path: str = "",
    loader: str = "",
    file_sha256: str = "",
) -> TrainingConfig:
    """Validate a document into a :class:`TrainingConfig`, or refuse it with a reason."""
    unknown = sorted(set(document) - set(_SECTIONS) - {"version"})
    if unknown:
        raise ConfigurationError(
            f"unknown top-level section(s) {', '.join(repr(item) for item in unknown)}; "
            f"a training configuration has {', '.join(sorted(_SECTIONS))}"
        )
    missing = [name for name in _REQUIRED_SECTIONS if name not in document]
    if missing:
        raise ConfigurationError(f"missing required section(s): {', '.join(missing)}")

    version = document.get("version", CONFIG_VERSION)
    if version != CONFIG_VERSION:
        raise ConfigurationError(
            f"version {version!r} is not supported; this build reads version {CONFIG_VERSION}"
        )

    model_section = _section(document, "model")
    base = _text(model_section, "base", "", where="model")
    if not base.strip():
        raise ConfigurationError("model.base is required")
    if _flag(model_section, "trust_remote_code", False, where="model"):
        raise ConfigurationError(
            "model.trust_remote_code must be false. Remote code is arbitrary code from a "
            "model author run with your privileges; Bunny Model Studio does not execute it."
        )
    model = ModelConfig(
        base=base.strip(),
        revision=_text(model_section, "revision", "main", where="model").strip() or "main",
        trust_remote_code=False,
    )

    training_section = _section(document, "training")
    batch_size: int | str = training_section.get("batch_size", "auto")
    if isinstance(batch_size, bool) or not isinstance(batch_size, (int, str)):
        raise ConfigurationError(f"training.batch_size: expected an integer or 'auto', found {batch_size!r}")
    if isinstance(batch_size, str) and batch_size != "auto":
        raise ConfigurationError(f"training.batch_size: {batch_size!r} is not an integer or 'auto'")
    if isinstance(batch_size, int) and not 1 <= batch_size <= 512:
        raise ConfigurationError(f"training.batch_size: {batch_size} is outside 1..512")

    training = TrainingParameters(
        method=_choice(training_section, "method", "lora", where="training", allowed=("lora", "qlora")),
        epochs=_integer(training_section, "epochs", 1, where="training", minimum=1, maximum=100),
        batch_size=batch_size,
        gradient_accumulation_steps=_integer(
            training_section, "gradient_accumulation_steps", 1, where="training", minimum=1, maximum=512
        ),
        learning_rate=_number(
            training_section, "learning_rate", 2e-4, where="training",
            minimum=0, maximum=1, exclusive_minimum=True,
        ),
        max_length=_integer(training_section, "max_length", 512, where="training", minimum=8, maximum=32768),
        gradient_checkpointing=_flag(training_section, "gradient_checkpointing", True, where="training"),
        precision=_choice(
            training_section, "precision", "auto", where="training",
            allowed=("auto", "bf16", "fp16", "fp32"),
        ),
        seed=_integer(training_section, "seed", 0, where="training", minimum=0, maximum=4294967295),
        max_steps=_integer(training_section, "max_steps", 0, where="training", minimum=0, maximum=1000000),
        warmup_steps=_integer(training_section, "warmup_steps", 0, where="training", minimum=0, maximum=100000),
    )

    quantization_section = _section(document, "quantization")
    quantization = QuantizationConfig(
        enabled=_flag(quantization_section, "enabled", False, where="quantization"),
        bits=_integer(quantization_section, "bits", 4, where="quantization", minimum=2, maximum=8),
        compute_dtype=_choice(
            quantization_section, "compute_dtype", "auto", where="quantization",
            allowed=("auto", "bf16", "fp16", "fp32"),
        ),
        double_quantization=_flag(quantization_section, "double_quantization", True, where="quantization"),
    )

    lora_section = _section(document, "lora")
    targets = lora_section.get("target_modules", [])
    if targets is None:
        targets = []
    if not isinstance(targets, (list, tuple)):
        raise ConfigurationError("lora.target_modules: expected a list of module names")
    for item in targets:
        if not isinstance(item, str) or not item.strip():
            raise ConfigurationError(f"lora.target_modules: {item!r} is not a module name")
    lora = LoraConfig(
        rank=_integer(lora_section, "rank", 16, where="lora", minimum=1, maximum=256),
        alpha=_integer(lora_section, "alpha", 32, where="lora", minimum=1, maximum=1024),
        dropout=_number(lora_section, "dropout", 0.05, where="lora", minimum=0, maximum=0.999),
        target_modules=tuple(str(item).strip() for item in targets),
        bias=_choice(lora_section, "bias", "none", where="lora", allowed=("none", "all", "lora_only")),
    )

    dataset_section = _section(document, "dataset")
    dataset_path = _text(dataset_section, "path", "", where="dataset")
    if not dataset_path.strip():
        raise ConfigurationError("dataset.path is required")
    if "://" in dataset_path:
        raise ConfigurationError(
            f"dataset.path {dataset_path!r} looks like a URL. A training corpus is the most "
            "private thing here and is not fetched over the network; give a local path."
        )
    dataset = DatasetConfig(
        path=dataset_path.strip(),
        format=_choice(dataset_section, "format", "chat", where="dataset", allowed=("chat",)),
        validation_split=_number(
            dataset_section, "validation_split", 0.0, where="dataset", minimum=0, maximum=0.9
        ),
        max_examples=_integer(
            dataset_section, "max_examples", 0, where="dataset", minimum=0, maximum=10000000
        ),
        policy_check=_flag(dataset_section, "policy_check", True, where="dataset"),
    )

    output_section = _section(document, "output")
    directory = _text(output_section, "directory", "", where="output")
    if not directory.strip():
        raise ConfigurationError("output.directory is required")
    output = OutputConfig(
        directory=directory.strip(),
        name=_text(output_section, "name", "", where="output").strip(),
        overwrite=_flag(output_section, "overwrite", False, where="output"),
    )

    _check_combinations(training, quantization, lora, dataset)

    return TrainingConfig(
        model=model,
        training=training,
        quantization=quantization,
        lora=lora,
        dataset=dataset,
        output=output,
        version=CONFIG_VERSION,
        source_path=source_path,
        loader=loader,
        file_sha256=file_sha256,
        base_directory=str(base_directory),
    )


def load_config(path: Path | str) -> TrainingConfig:
    """Load and validate a configuration file.

    Relative paths inside the document resolve against the *document's*
    directory, not the working directory. A configuration that only works when
    run from one place is a configuration that will one day be run from another.
    """
    file = Path(path).resolve()
    document, data, loader = load_document(file)
    return config_from_mapping(
        document,
        base_directory=file.parent,
        source_path=str(file),
        loader=loader,
        file_sha256=hashlib.sha256(data).hexdigest(),
    )
