# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Simulated hardware inventories, for tests and for ``--simulate``.

These are the seven machines §16 requires an integration test for, plus the
degenerate cases that break naive detection code. They are constructed as real
:class:`~capability.model.Inventory` values rather than as JSON fixtures so that
a change to the model breaks them at import time instead of producing a subtly
wrong inventory that still parses.

They are **simulations and are labelled as such everywhere they surface**. A
plan produced from one of these is a statement about the policy engine, never a
statement about hardware. No claim about any physical device is made anywhere in
this module or by anything that consumes it.
"""

from __future__ import annotations

from typing import Callable, Mapping

from .model import (
    AcceleratorFacts,
    AudioFacts,
    CpuFacts,
    DisplayFacts,
    GpuFacts,
    Inventory,
    MemoryFacts,
    NetworkFacts,
    PowerFacts,
    ProbeOutcome,
    StorageFacts,
    SystemFacts,
    ThermalFacts,
    absent,
    measured,
    unknown,
)

__all__ = ["MACHINES", "describe", "simulate"]

_MIB = 1024 ** 2
_GIB = 1024 ** 3
_SIMULATED = "simulated"

#: Every probe reported as having completed, so that score functions which
#: distinguish "probed and found nothing" from "never probed" behave as they
#: would on a real machine. A simulation that left probes unrecorded would make
#: ``gpu_compute`` return ``None`` on every machine, including the ones that
#: genuinely have no GPU.
_PROBES = tuple(
    ProbeOutcome(name, "ok", 0, "simulated")
    for name in ("system", "memory", "cpu", "storage", "display", "power",
                 "thermal", "audio", "network", "gpu", "accelerators")
)


def _gpu(
    index: int,
    vendor: str,
    kind: str,
    driver: str | None,
    vram_bytes: int | None,
    *,
    render_node: str | None = None,
    cuda: bool = False,
    rocm: bool = False,
    vulkan: bool = False,
) -> GpuFacts:
    """One simulated device. ``driver=None`` models the present-but-unusable case."""
    return GpuFacts(
        index=index,
        vendor=measured(vendor, _SIMULATED),
        device_id=measured(f"0x{1000 + index:04x}", _SIMULATED),
        description=measured(f"{vendor} device {index}", _SIMULATED),
        kind=measured(kind, _SIMULATED),
        driver=measured(driver, _SIMULATED) if driver else absent(_SIMULATED, "no driver is bound to this device"),
        render_node=(
            measured(render_node or f"renderD{128 + index}", _SIMULATED)
            if driver
            else absent(_SIMULATED, "no render node was created for this card")
        ),
        vram_total_bytes=(
            measured(vram_bytes, _SIMULATED) if vram_bytes
            else absent(_SIMULATED, "shares system memory; there is no dedicated pool")
        ),
        vram_available_bytes=(
            measured(int(vram_bytes * 0.9), _SIMULATED) if vram_bytes
            else absent(_SIMULATED, "shares system memory")
        ),
        runtimes={
            "cuda": measured(cuda, _SIMULATED),
            "rocm": measured(rocm, _SIMULATED),
            "vulkan": measured(vulkan, _SIMULATED),
            "opencl": measured(cuda or rocm, _SIMULATED),
        },
    )


def machine(
    *,
    architecture: str = "x86_64",
    physical_memory_bytes: int,
    available_memory_bytes: int | None = None,
    cgroup_memory_limit_bytes: int | None = None,
    logical_threads: int = 4,
    physical_cores: int | None = None,
    quota_cores: float | None = None,
    instruction_sets: tuple[str, ...] = ("sse4_2", "avx2"),
    load_average: float = 0.1,
    gpus: tuple[GpuFacts, ...] = (),
    accelerators: tuple[AcceleratorFacts, ...] = (),
    storage_total_bytes: int = 64 * _GIB,
    storage_available_bytes: int | None = None,
    filesystem: str = "ext4",
    read_only: bool = False,
    storage_class: str | None = "solid-state",
    online: bool = True,
    connection_type: str | None = "wired",
    metered: bool | None = False,
    power_supply: str = "ac",
    battery_percent: int | None = None,
    throttled: bool = False,
    cooling_state: float = 0.0,
    connected_outputs: int = 1,
    resolution: str | None = "1920x1080",
    keyboard: bool = True,
    pointer: bool = True,
    touch: bool = False,
    audio_output: bool = True,
    audio_input: bool = True,
    camera: bool = False,
    containerized: bool = False,
    virtualized: bool = False,
    memory_pressure: float = 0.0,
) -> Inventory:
    """Build a complete simulated inventory from plain values."""
    usable = min(physical_memory_bytes, cgroup_memory_limit_bytes or physical_memory_bytes)
    available = available_memory_bytes if available_memory_bytes is not None else int(usable * 0.7)
    storage_available = storage_available_bytes if storage_available_bytes is not None else int(storage_total_bytes * 0.5)

    return Inventory(
        detected_at="2026-01-01T00:00:00Z",
        system=SystemFacts(
            architecture=measured(architecture, _SIMULATED),
            kernel_release=measured("6.14.0-simulated", _SIMULATED),
            virtualized=measured(virtualized, _SIMULATED),
            containerized=measured(containerized, _SIMULATED),
            container_runtime=measured("podman", _SIMULATED) if containerized else absent(_SIMULATED),
            boot_id_present=measured(True, _SIMULATED),
        ),
        cpu=CpuFacts(
            vendor=measured("simulated", _SIMULATED),
            model=measured(f"Simulated {architecture} CPU", _SIMULATED),
            physical_cores=measured(physical_cores or max(1, logical_threads // 2), _SIMULATED),
            logical_threads=measured(logical_threads, _SIMULATED),
            instruction_sets=measured(sorted(instruction_sets), _SIMULATED),
            max_frequency_hz=measured(3_000_000_000, _SIMULATED),
            virtualization_supported=measured(not containerized, _SIMULATED),
            quota_cores=measured(quota_cores, _SIMULATED) if quota_cores is not None else absent(_SIMULATED, "no cgroup cpu quota"),
            load_average_1m=measured(load_average, _SIMULATED),
            frequency_throttled=measured(throttled, _SIMULATED),
        ),
        memory=MemoryFacts(
            physical_bytes=measured(physical_memory_bytes, _SIMULATED),
            available_bytes=measured(available, _SIMULATED),
            cgroup_limit_bytes=(
                measured(cgroup_memory_limit_bytes, _SIMULATED) if cgroup_memory_limit_bytes
                else absent(_SIMULATED, "no cgroup memory limit")
            ),
            cgroup_usage_bytes=absent(_SIMULATED, "not simulated"),
            swap_total_bytes=measured(0, _SIMULATED),
            swap_free_bytes=measured(0, _SIMULATED),
            pressure_some_avg10=measured(memory_pressure, _SIMULATED),
            reserved_bytes=unknown(_SIMULATED, "not simulated"),
        ),
        gpu=gpus,
        accelerators=accelerators,
        storage=StorageFacts(
            root_total_bytes=measured(storage_total_bytes, _SIMULATED),
            root_available_bytes=measured(storage_available, _SIMULATED),
            filesystem=measured(filesystem, _SIMULATED),
            read_only=measured(read_only, _SIMULATED),
            storage_class=measured(storage_class, _SIMULATED) if storage_class else unknown(_SIMULATED, "class not determinable"),
            io_pressure_some_avg10=measured(0.0, _SIMULATED),
            temporary_available_bytes=measured(min(storage_available, 4 * _GIB), _SIMULATED),
        ),
        network=NetworkFacts(
            interfaces_present=measured(1 if online else 0, _SIMULATED),
            carrier_up=measured(online, _SIMULATED),
            default_route=measured(online, _SIMULATED),
            connection_type=measured(connection_type, _SIMULATED) if online and connection_type else absent(_SIMULATED, "no default route"),
            metered=measured(metered, _SIMULATED) if metered is not None else unknown(_SIMULATED, "metering not determinable"),
            endpoint_reachable=unknown(_SIMULATED, "reachability probing is opt-in and was not requested"),
            latency_ms=unknown(_SIMULATED, "no probe was attempted"),
            bandwidth_bits_per_second=unknown(_SIMULATED, "no bandwidth probe exists"),
        ),
        power=PowerFacts(
            supply=measured(power_supply, _SIMULATED),
            battery_present=measured(battery_percent is not None, _SIMULATED),
            battery_percent=measured(battery_percent, _SIMULATED) if battery_percent is not None else absent(_SIMULATED, "no battery"),
            power_saving=measured(False, _SIMULATED),
        ),
        thermal=ThermalFacts(
            max_celsius=measured(45.0, _SIMULATED),
            throttled=measured(throttled, _SIMULATED),
            cooling_state=measured(cooling_state, _SIMULATED),
        ),
        display=DisplayFacts(
            headless=measured(connected_outputs == 0, _SIMULATED),
            connected_outputs=measured(connected_outputs, _SIMULATED),
            max_resolution=measured(resolution, _SIMULATED) if resolution and connected_outputs else absent(_SIMULATED, "no connected connector"),
            touch=measured(touch, _SIMULATED),
            keyboard=measured(keyboard, _SIMULATED),
            pointer=measured(pointer, _SIMULATED),
        ),
        audio=AudioFacts(
            output_present=measured(audio_output, _SIMULATED),
            input_present=measured(audio_input, _SIMULATED),
            camera_present=measured(camera, _SIMULATED),
        ),
        probes=_PROBES,
        detection_budget_ms=2000,
        detection_duration_ms=0,
    )


# --------------------------------------------------------------------------- #
# The seven required machines, plus the cases that break naive detection
# --------------------------------------------------------------------------- #


def _embedded_64mb() -> Inventory:
    """§5's explicit constraint: 64 MB of RAM, headless, one core, ARM."""
    return machine(
        architecture="aarch64",
        physical_memory_bytes=64 * _MIB,
        available_memory_bytes=44 * _MIB,
        logical_threads=1,
        physical_cores=1,
        instruction_sets=(),
        storage_total_bytes=512 * _MIB,
        storage_available_bytes=180 * _MIB,
        filesystem="squashfs",
        storage_class="solid-state",
        connected_outputs=0,
        resolution=None,
        keyboard=False,
        pointer=False,
        audio_output=False,
        audio_input=False,
        connection_type="wired",
    )


def _raspberry_pi_class() -> Inventory:
    """A 1 GB single-board computer with a shared-memory GPU and a display."""
    return machine(
        architecture="aarch64",
        physical_memory_bytes=1 * _GIB,
        available_memory_bytes=700 * _MIB,
        logical_threads=4,
        physical_cores=4,
        instruction_sets=("asimd",),
        gpus=(_gpu(0, "broadcom", "integrated", "v3d", None, vulkan=True),),
        storage_total_bytes=32 * _GIB,
        storage_available_bytes=20 * _GIB,
        storage_class="solid-state",
        connected_outputs=1,
        resolution="1920x1080",
        connection_type="wireless",
        audio_input=False,
    )


def _laptop() -> Inventory:
    """A mainstream laptop: 16 GB, integrated graphics, on battery."""
    return machine(
        physical_memory_bytes=16 * _GIB,
        available_memory_bytes=9 * _GIB,
        logical_threads=8,
        physical_cores=4,
        instruction_sets=("sse4_2", "avx", "avx2", "aes"),
        gpus=(_gpu(0, "intel", "integrated", "i915", None, vulkan=True),),
        storage_total_bytes=512 * _GIB,
        storage_available_bytes=200 * _GIB,
        power_supply="battery",
        battery_percent=72,
        connection_type="wireless",
        touch=True,
        camera=True,
    )


def _gaming_desktop() -> Inventory:
    """A discrete-GPU workstation: 32 GB, one 16 GB card, mains power."""
    return machine(
        physical_memory_bytes=32 * _GIB,
        available_memory_bytes=24 * _GIB,
        logical_threads=16,
        physical_cores=8,
        instruction_sets=("sse4_2", "avx", "avx2", "aes", "fma"),
        gpus=(_gpu(0, "nvidia", "discrete", "nvidia", 16 * _GIB, cuda=True, vulkan=True),),
        storage_total_bytes=2048 * _GIB,
        storage_available_bytes=900 * _GIB,
        connected_outputs=2,
        resolution="3840x2160",
        camera=True,
    )


def _cpu_server() -> Inventory:
    """A headless server: 64 GB, 64 threads, no GPU, no display, no audio."""
    return machine(
        physical_memory_bytes=64 * _GIB,
        available_memory_bytes=58 * _GIB,
        logical_threads=64,
        physical_cores=32,
        instruction_sets=("sse4_2", "avx", "avx2", "avx512f", "aes", "fma"),
        storage_total_bytes=4096 * _GIB,
        storage_available_bytes=3000 * _GIB,
        connected_outputs=0,
        resolution=None,
        keyboard=False,
        pointer=False,
        audio_output=False,
        audio_input=False,
        load_average=6.0,
    )


def _multi_gpu_ai_server() -> Inventory:
    """A DGX-class machine: 512 GB, eight 80 GB accelerators, headless."""
    return machine(
        physical_memory_bytes=512 * _GIB,
        available_memory_bytes=480 * _GIB,
        logical_threads=128,
        physical_cores=64,
        instruction_sets=("sse4_2", "avx", "avx2", "avx512f", "amx_int8", "aes", "fma"),
        gpus=tuple(
            _gpu(index, "nvidia", "discrete", "nvidia", 80 * _GIB, cuda=True, vulkan=True)
            for index in range(8)
        ),
        storage_total_bytes=16384 * _GIB,
        storage_available_bytes=12000 * _GIB,
        connected_outputs=0,
        resolution=None,
        keyboard=False,
        pointer=False,
        audio_output=False,
        audio_input=False,
        load_average=12.0,
    )


def _constrained_container() -> Inventory:
    """The case that catches every detector that trusts ``MemTotal``.

    A 512 MB, half-a-core cgroup on a 512 GB, 128-thread host with eight GPUs.
    Read the physical numbers and this machine looks like a supercomputer; read
    the ceilings and it is smaller than a phone. Everything downstream is
    required to reach the second conclusion.
    """
    return machine(
        physical_memory_bytes=512 * _GIB,
        available_memory_bytes=480 * _GIB,
        cgroup_memory_limit_bytes=512 * _MIB,
        logical_threads=128,
        physical_cores=64,
        quota_cores=0.5,
        instruction_sets=("sse4_2", "avx", "avx2", "avx512f"),
        gpus=tuple(
            _gpu(index, "nvidia", "discrete", "nvidia", 80 * _GIB, cuda=True, vulkan=True)
            for index in range(8)
        ),
        storage_total_bytes=100 * _GIB,
        storage_available_bytes=40 * _GIB,
        containerized=True,
        connected_outputs=0,
        resolution=None,
        keyboard=False,
        pointer=False,
        audio_output=False,
        audio_input=False,
    )


def _gpu_without_driver() -> Inventory:
    """A discrete card the kernel never bound a driver to."""
    return machine(
        physical_memory_bytes=16 * _GIB,
        logical_threads=8,
        gpus=(_gpu(0, "nvidia", "discrete", None, None),),
    )


def _offline_laptop() -> Inventory:
    return machine(
        physical_memory_bytes=8 * _GIB,
        logical_threads=4,
        gpus=(_gpu(0, "intel", "integrated", "i915", None, vulkan=True),),
        online=False,
        connection_type=None,
        metered=None,
        power_supply="battery",
        battery_percent=15,
    )


def _read_only_appliance() -> Inventory:
    return machine(
        physical_memory_bytes=2 * _GIB,
        logical_threads=2,
        storage_total_bytes=8 * _GIB,
        storage_available_bytes=1 * _GIB,
        filesystem="squashfs",
        read_only=True,
        connected_outputs=0,
        resolution=None,
        keyboard=False,
        pointer=False,
    )


def _unmeasurable() -> Inventory:
    """Every probe ran and every probe failed.

    Not a machine anyone owns; a machine every layer downstream must survive.
    Nothing is known, nothing may be assumed, and the correct behaviour is to
    refuse optional work rather than to crash or to guess.
    """
    return Inventory(
        detected_at="2026-01-01T00:00:00Z",
        probes=tuple(
            ProbeOutcome(item.name, "failed", 0, "simulated total probe failure")
            for item in _PROBES
        ),
        detection_budget_ms=2000,
        detection_duration_ms=0,
    )


#: Name -> factory. The first seven are §16's required integration machines.
MACHINES: Mapping[str, Callable[[], Inventory]] = {
    "embedded-64mb": _embedded_64mb,
    "raspberry-pi-class": _raspberry_pi_class,
    "laptop": _laptop,
    "gaming-desktop": _gaming_desktop,
    "cpu-server": _cpu_server,
    "multi-gpu-ai-server": _multi_gpu_ai_server,
    "constrained-container": _constrained_container,
    "gpu-without-driver": _gpu_without_driver,
    "offline-laptop": _offline_laptop,
    "read-only-appliance": _read_only_appliance,
    "unmeasurable": _unmeasurable,
}

_DESCRIPTIONS: Mapping[str, str] = {
    "embedded-64mb": "64 MB headless ARM board, one core, read-mostly storage",
    "raspberry-pi-class": "1 GB ARM single-board computer with a shared-memory GPU and a display",
    "laptop": "16 GB laptop on battery with integrated graphics",
    "gaming-desktop": "32 GB desktop with one 16 GB discrete GPU",
    "cpu-server": "64 GB, 64-thread headless server with no GPU",
    "multi-gpu-ai-server": "512 GB headless server with eight 80 GB accelerators",
    "constrained-container": "512 MB / 0.5 core container on a 512 GB, eight-GPU host",
    "gpu-without-driver": "discrete GPU present with no driver bound",
    "offline-laptop": "8 GB laptop with no default route and a low battery",
    "read-only-appliance": "2 GB appliance with a read-only root filesystem",
    "unmeasurable": "every probe ran and every probe failed",
}


def describe(name: str) -> str:
    return _DESCRIPTIONS.get(name, "")


def simulate(name: str) -> Inventory:
    """One simulated inventory by name."""
    factory = MACHINES.get(name)
    if factory is None:
        raise KeyError(f"unknown simulated machine {name!r}; known: {sorted(MACHINES)}")
    return factory()
