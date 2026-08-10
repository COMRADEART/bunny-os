# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Private Pocket/Kitten inference worker for Bunny Voice.

This file is executed by ``/usr/bin/bunny-voice-neural-worker`` in a dedicated
process.  Importing it never imports either neural runtime.  The process accepts
one bounded JSON object per line, keeps one selected model resident, writes only
private PCM WAV artifacts, and never opens a network connection or an audio
device.  Playback remains owned by the parent AudioRouter.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import wave
from typing import Any, Mapping


MAX_MESSAGE_BYTES = 64 * 1024
MAX_TEXT_CHARACTERS = 4000
MAX_CHUNKS = 64
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,95}\Z")
_TEXT_TOKENS = re.compile(r"\w+|[^\w\s]")
#: The header eSpeak NG prints when an argument made it list voices instead of
#: phonemizing. Matched so that output is refused rather than spoken.
_VOICE_TABLE = re.compile(r"^\s*Pty\s+Language\s+Age/Gender", re.MULTILINE)


def _runtime_site() -> Path:
    configured = os.environ.get("BUNNY_VOICE_RUNTIME_SITE", "").strip()
    return Path(configured) if configured else Path("/usr/lib/bunny-os/voice-runtime/site-packages")


def _install_runtime_path() -> None:
    runtime = _runtime_site()
    if runtime.is_dir():
        sys.path.insert(0, str(runtime))


def _disable_network_environment() -> None:
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    os.environ["NO_PROXY"] = "*"
    os.environ["no_proxy"] = "*"
    for name in (
        "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy",
    ):
        os.environ.pop(name, None)


def _manifest(root: Path, expected_digest: str, provider_id: str, model_id: str) -> Mapping[str, Any]:
    manifest = root / "manifest.json"
    raw = manifest.read_bytes()
    if len(raw) > 256 * 1024 or hashlib.sha256(raw).hexdigest() != expected_digest:
        raise ValueError("model manifest digest mismatch")
    document = json.loads(raw.decode("utf-8"))
    if (
        not isinstance(document, Mapping)
        or document.get("schemaVersion") != 1
        or document.get("providerId") != provider_id
        or document.get("modelId") != model_id
    ):
        raise ValueError("model manifest identity mismatch")
    return document


def _relative_file(root: Path, raw: Any) -> Path:
    if not isinstance(raw, str) or not raw or "\0" in raw:
        raise ValueError("invalid relative model path")
    relative = Path(raw)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("model path escapes its installation")
    path = (root / relative).resolve(strict=True)
    path.relative_to(root.resolve(strict=True))
    if not path.is_file():
        raise ValueError("model path is not a file")
    return path


def _private_output(raw: Any) -> Path:
    if not isinstance(raw, str) or not raw or "\0" in raw:
        raise ValueError("invalid output path")
    path = Path(raw)
    if not path.is_absolute() or path.suffix != ".wav":
        raise ValueError("output must be an absolute WAV path")
    parent = path.parent.resolve(strict=True)
    if not parent.name.startswith("bunny-voice-"):
        raise ValueError("output is outside a Bunny private voice workspace")
    resolved = path.resolve(strict=False)
    if resolved.parent != parent or path.is_symlink():
        raise ValueError("output path is indirect")
    return path


def _chunks(document: Mapping[str, Any]) -> tuple[str, ...]:
    raw = document.get("chunks")
    if not isinstance(raw, list) or not 1 <= len(raw) <= MAX_CHUNKS:
        raise ValueError("a synthesis request needs a bounded chunk list")
    chunks: list[str] = []
    total = 0
    for item in raw:
        if not isinstance(item, str):
            raise ValueError("a speech chunk is not text")
        body = " ".join(item.split())
        if not body or len(body) > 512:
            raise ValueError("a speech chunk is empty or oversized")
        total += len(body)
        chunks.append(body)
    if total > MAX_TEXT_CHARACTERS:
        raise ValueError("speech text is oversized")
    return tuple(chunks)


def _resample(audio: Any, source_rate: int, target_rate: int) -> Any:
    import numpy as np

    values = np.asarray(audio, dtype=np.float32).reshape(-1)
    if source_rate == target_rate or values.size < 2:
        return values
    length = max(1, int(round(values.size * target_rate / source_rate)))
    source = np.arange(values.size, dtype=np.float64)
    target = np.linspace(0.0, float(values.size - 1), num=length, dtype=np.float64)
    return np.interp(target, source, values).astype(np.float32)


def _write_wav(path: Path, audio: Any, sample_rate: int) -> tuple[int, float]:
    import numpy as np

    values = np.asarray(audio, dtype=np.float32).reshape(-1)
    if values.size <= 0 or not np.isfinite(values).all():
        raise ValueError("synthesis returned no finite samples")
    pcm = (np.clip(values, -1.0, 1.0) * 32767.0).astype("<i2", copy=False)
    partial = path.with_name(path.name + ".partial")
    descriptor = os.open(partial, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            with wave.open(stream, "wb") as output:
                output.setnchannels(1)
                output.setsampwidth(2)
                output.setframerate(sample_rate)
                output.writeframes(pcm.tobytes())
        os.replace(partial, path)
        os.chmod(path, 0o600)
    finally:
        try:
            partial.unlink()
        except FileNotFoundError:
            pass
    return int(pcm.size), float(pcm.size / sample_rate)


class _PocketEngine:
    provider_id = "pocket"

    def __init__(self, root: Path, voice_path: Path) -> None:
        from pocket_tts import TTSModel

        config = root / "config.yaml"
        if not config.is_file():
            raise FileNotFoundError("Pocket config.yaml is absent")
        previous = Path.cwd()
        try:
            # Pocket 2.1 resolves non-hf weight paths against cwd rather than the
            # config directory.  The bundled config contains only relative local
            # paths, so this cannot trigger a download.
            os.chdir(root)
            self.model = TTSModel.load_model(config=config)
        finally:
            os.chdir(previous)
        # The bundled weights are the official no-cloning build.  Pocket's
        # loader infers this flag from a failed gated download, but Bunny uses
        # an explicit local path and never attempts that download.  Set the
        # capability to the truth so even an accidental future raw-audio call
        # fails inside the isolated worker; prepared .safetensors voices remain
        # supported by Pocket before that guard.
        self.model.has_voice_cloning = False
        self.sample_rate = int(self.model.sample_rate)
        self._voices: dict[str, Any] = {}
        self.load_voice(voice_path.stem, voice_path)

    def load_voice(self, voice_id: str, voice_path: Path) -> Any:
        state = self._voices.get(voice_id)
        if state is None:
            state = self.model.get_state_for_audio_prompt(voice_path)
            self._voices[voice_id] = state
        return state

    def generate(self, chunks: tuple[str, ...], voice_id: str, voice_path: Path, _rate: float) -> Any:
        import torch

        state = self.load_voice(voice_id, voice_path)
        generated = [self.model.generate_audio(state, chunk, copy_state=True) for chunk in chunks]
        if not generated:
            raise ValueError("Pocket produced no chunks")
        return torch.cat([item.reshape(-1) for item in generated]).detach().cpu().numpy()


class _TextCleaner:
    """Kitten 0.8.1's public token inventory, retained byte-for-byte in meaning."""

    def __init__(self) -> None:
        # Every character here is an *index*, not a decoration. The model was
        # trained against this exact ordering, so dropping one shifts every
        # symbol after it and the model reads a different phoneme than the one
        # eSpeak produced. The two curly double quotes are easy to lose to a
        # copy through a smart-quote-aware editor and cost nothing visible: the
        # audio stays fluent and confident and simply says something else.
        punctuation = ';:,.!?¡¿—…"«»“” '
        letters = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
        ipa = "ɑɐɒæɓʙβɔɕçɗɖðʤəɘɚɛɜɝɞɟʄɡɠɢʛɦɧħɥʜɨɪʝɭɬɫɮʟɱɯɰŋɳɲɴøɵɸθœɶʘɹɺɾɻʀʁɽʂʃʈʧʉʊʋⱱʌɣɤʍχʎʏʑʐʒʔʡʕʢǀǁǂǃˈˌːˑʼʴʰʱʲʷˠˤ˞↓↑→↗↘'̩'ᵻ"
        symbols = ["$"] + list(punctuation) + list(letters) + list(ipa)
        self._indices = {character: index for index, character in enumerate(symbols)}

    def __call__(self, text: str) -> list[int]:
        return [self._indices[character] for character in text if character in self._indices]

    def retain_known(self, text: str) -> str:
        """Drop characters the model has no index for, *before* tokenization.

        Dropping them afterwards is too late. ``_TEXT_TOKENS`` classifies any
        non-word non-space character as its own token, and the tokens are then
        joined with spaces — so an unknown character does not merely get
        ignored, it injects a space where there was none. Space is a real index
        in this vocabulary, so ``həlˈoʊ`` phonemized with ``--ipa=3`` ties
        becomes ``həlˈo ‍ ʊ`` and the model reads a word boundary inside every
        diphthong. Measured on "Hello. I am Bunny, and your system is ready.":
        word error rate 0.44 and 5.59s of audio with the ties left in, 0.00 and
        4.09s with them removed here.
        """
        return "".join(
            character for character in text
            if character in self._indices or character.isspace()
        )


class _KittenEngine:
    provider_id = "kitten"
    sample_rate = 24_000

    def __init__(self, root: Path, _voice_path: Path) -> None:
        import numpy as np
        import onnxruntime as ort

        config_path = root / "config.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        if not isinstance(config, Mapping) or config.get("type") not in ("ONNX1", "ONNX2"):
            raise ValueError("unsupported Kitten model configuration")
        model_path = _relative_file(root, config.get("model_file"))
        voices_path = _relative_file(root, config.get("voices"))
        self.session = ort.InferenceSession(str(model_path), providers=["CPUExecutionProvider"])
        self.voices = np.load(voices_path)
        self.speed_priors = dict(config.get("speed_priors") or {})
        self.voice_aliases = dict(config.get("voice_aliases") or {})
        self.cleaner = _TextCleaner()

    @staticmethod
    def _phonemize(text: str) -> str:
        executable = "/usr/bin/espeak-ng"
        if not Path(executable).is_file():
            raise FileNotFoundError("eSpeak NG is required for Kitten phonemization")
        completed = subprocess.run(  # noqa: S603 - fixed executable and argument array
            # Every element of this array is load-bearing, and eSpeak NG 1.52
            # punishes each mistake by *succeeding*:
            #
            # ``-q``          the long ``--quiet`` does not exist. Given it,
            #                 eSpeak prints "unrecognized option" and exits 0.
            #                 Without ``-q`` at all it opens an audio device and
            #                 returns only the first clause.
            # ``-v en-us``    as two arguments. ``--voice=en-us`` is prefix
            #                 matched to ``--voices`` and prints the whole voice
            #                 *table* to stdout, also with status 0 — which is
            #                 non-empty output that would be phonemized and
            #                 spoken as if the table were the utterance.
            [executable, "-q", "--ipa=3", "-v", "en-us", "--stdin"],
            input=text.encode("utf-8"),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=15.0,
            shell=False,
            env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"},
        )
        # The exit status is therefore not evidence that anything was
        # phonemized, so it is only the first of three checks rather than the
        # only one. A rejected argument leaves its complaint on stderr, and a
        # listing leaves the table's header on stdout.
        if completed.returncode != 0 or not completed.stdout:
            raise RuntimeError("Kitten phonemization failed")
        if b"unrecognized option" in completed.stderr or b"invalid option" in completed.stderr:
            raise RuntimeError("Kitten phonemization rejected an argument")
        phonemes = completed.stdout.decode("utf-8", errors="strict").strip()
        if _VOICE_TABLE.search(phonemes):
            raise RuntimeError("Kitten phonemization returned a voice listing rather than phonemes")
        return phonemes

    def _one(self, text: str, voice_id: str, rate: float) -> Any:
        import numpy as np

        key = self.voice_aliases.get(voice_id, voice_id)
        if key not in self.voices.files:
            raise ValueError("the selected Kitten voice is absent")
        effective_rate = float(rate) * float(self.speed_priors.get(key, 1.0))
        phonemes = " ".join(_TEXT_TOKENS.findall(self.cleaner.retain_known(self._phonemize(text))))
        tokens = self.cleaner(phonemes)
        if not tokens:
            raise ValueError("Kitten phonemization returned no tokens")
        tokens.insert(0, 0)
        tokens.extend((10, 0))
        input_ids = np.array([tokens], dtype=np.int64)
        reference = min(len(text), self.voices[key].shape[0] - 1)
        style = self.voices[key][reference:reference + 1]
        output = self.session.run(None, {
            "input_ids": input_ids,
            "style": style,
            "speed": np.array([effective_rate], dtype=np.float32),
        })[0]
        return np.asarray(output)[..., :-5000].reshape(-1)

    def generate(self, chunks: tuple[str, ...], voice_id: str, _voice_path: Path, rate: float) -> Any:
        import numpy as np

        return np.concatenate([self._one(chunk, voice_id, rate) for chunk in chunks])


class Worker:
    def __init__(self, provider_id: str) -> None:
        if provider_id not in ("pocket", "kitten"):
            raise ValueError("unsupported neural provider")
        self.provider_id = provider_id
        self.model_id = ""
        self.root: Path | None = None
        self.engine: Any = None
        self.voices: dict[str, Path] = {}

    def initialize(self, document: Mapping[str, Any]) -> dict[str, Any]:
        provider_id = str(document.get("providerId") or "")
        model_id = str(document.get("modelId") or "")
        voice_id = str(document.get("voiceId") or "")
        if provider_id != self.provider_id or not _SAFE_ID.match(model_id) or not _SAFE_ID.match(voice_id):
            raise ValueError("invalid provider, model or voice identity")
        root = Path(str(document.get("modelRoot") or ""))
        if not root.is_absolute():
            raise ValueError("model root is not absolute")
        root = root.resolve(strict=True)
        _manifest(root, str(document.get("manifestDigest") or ""), provider_id, model_id)
        voice_path = _relative_file(root, document.get("voicePath"))
        if self.engine is None or self.model_id != model_id or self.root != root:
            engine_type = _PocketEngine if provider_id == "pocket" else _KittenEngine
            self.engine = engine_type(root, voice_path)
            self.model_id = model_id
            self.root = root
            self.voices = {}
        self.voices[voice_id] = voice_path
        if provider_id == "pocket":
            self.engine.load_voice(voice_id, voice_path)
        return {
            "ready": True,
            "providerId": provider_id,
            "modelId": model_id,
            "voiceId": voice_id,
            "sampleRate": int(self.engine.sample_rate),
            "detail": "local model and prepared voice initialized",
        }

    def synthesize(self, document: Mapping[str, Any]) -> dict[str, Any]:
        provider_id = str(document.get("providerId") or "")
        model_id = str(document.get("modelId") or "")
        generation_id = str(document.get("generationId") or "")
        request_id = str(document.get("requestId") or "")
        voice_id = str(document.get("voiceId") or "")
        if (
            self.engine is None or provider_id != self.provider_id or model_id != self.model_id
            or not _SAFE_ID.match(generation_id) or not _SAFE_ID.match(request_id)
            or not _SAFE_ID.match(voice_id)
        ):
            raise ValueError("synthesis identity is invalid or the model is not initialized")
        root = self.root
        assert root is not None
        voice_path = _relative_file(root, document.get("voicePath"))
        if voice_id not in self.voices or self.voices[voice_id] != voice_path:
            self.voices[voice_id] = voice_path
            if provider_id == "pocket":
                self.engine.load_voice(voice_id, voice_path)
        chunks = _chunks(document)
        rate = float(document.get("speakingRate", 1.0))
        target_rate = int(document.get("sampleRate", 22_050))
        if not 0.25 <= rate <= 4.0 or target_rate not in (16_000, 22_050, 24_000, 44_100, 48_000):
            raise ValueError("unsupported synthesis rate")
        output = _private_output(document.get("outputPath"))
        started = __import__("time").monotonic()
        audio = self.engine.generate(chunks, voice_id, voice_path, rate)
        audio = _resample(audio, int(self.engine.sample_rate), target_rate)
        frames, duration = _write_wav(output, audio, target_rate)
        elapsed = __import__("time").monotonic() - started
        return {
            "succeeded": True,
            "providerId": provider_id,
            "modelId": model_id,
            "voiceId": voice_id,
            "generationId": generation_id,
            "sampleRate": target_rate,
            "frameCount": frames,
            "durationSeconds": duration,
            "synthesisSeconds": elapsed,
        }

    def dispatch(self, document: Mapping[str, Any]) -> dict[str, Any]:
        operation = document.get("op")
        if operation == "initialize":
            return self.initialize(document)
        if operation == "synthesize":
            return self.synthesize(document)
        if operation == "unload":
            self.engine = None
            self.model_id = ""
            self.root = None
            self.voices = {}
            return {"unloaded": True, "providerId": self.provider_id}
        raise ValueError("unknown neural worker operation")


def _reply(document: Mapping[str, Any]) -> None:
    payload = json.dumps(document, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
    if len(payload) > MAX_MESSAGE_BYTES:
        payload = b'{"succeeded":false,"detail":"worker response exceeded its bound"}'
    sys.stdout.buffer.write(payload + b"\n")
    sys.stdout.buffer.flush()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--provider", choices=("pocket", "kitten"), required=True)
    arguments = parser.parse_args(argv)
    _disable_network_environment()
    _install_runtime_path()
    worker = Worker(arguments.provider)
    for raw in sys.stdin.buffer:
        if not raw or len(raw) > MAX_MESSAGE_BYTES:
            _reply({"succeeded": False, "ready": False, "detail": "worker request exceeded its bound"})
            continue
        document: Any = None
        try:
            document = json.loads(raw.decode("utf-8"))
            if not isinstance(document, Mapping):
                raise ValueError("worker request is not an object")
            answer = worker.dispatch(document)
        except Exception as exc:  # noqa: BLE001 - one generation must not kill the worker
            # Do not include the exception string: model libraries sometimes
            # quote their text input in an error, and speech text is never a log
            # or diagnostic field.  The class still identifies the failure.
            answer = {
                "succeeded": False,
                "ready": False,
                "providerId": arguments.provider,
                "generationId": str(document.get("generationId") or "") if isinstance(document, Mapping) else "",
                "detail": f"neural worker {type(exc).__name__}",
            }
        _reply(answer)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
