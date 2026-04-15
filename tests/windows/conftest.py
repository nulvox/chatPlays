"""Fixtures for Windows controller tests.

These tests run inside a Windows Server VM where ViGEmBus + xusb21 are
installed.  On Server editions the first ``vigem_target_add`` after boot
fails because PnP has not yet bound the xusb21 driver to the Xbox 360
hardware ID.  We monkey-patch ``VGamepad.__init__`` to retry, which
lets PnP catch up.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Literal

import pytest


# ── vgamepad Windows-Server PnP retry patch ─────────────────────────────────

def _patch_vgamepad_retry() -> None:
    """Patch VGamepad.__init__ to retry vigem_target_add on PnP timing failures."""
    try:
        import vgamepad.win.vigem_client as vcli
        import vgamepad.win.vigem_commons as vcom
        import vgamepad.win.virtual_gamepad as vgmod
    except ImportError:
        return  # not on Windows / vgamepad not installed

    _PLUGGED_ERR = 0xE0000007  # VIGEM_ERROR_TARGET_NOT_PLUGGED_IN

    _orig_init = vgmod.VGamepad.__init__

    def _retrying_init(self):  # type: ignore[no-untyped-def]
        self.vbus = vgmod.VBUS
        self._busp = self.vbus.get_busp()
        self._devicep = self.target_alloc()
        self.CMPFUNC = vgmod.CFUNCTYPE(
            None, vgmod.c_void_p, vgmod.c_void_p,
            vgmod.c_ubyte, vgmod.c_ubyte, vgmod.c_ubyte, vgmod.c_void_p,
        )
        self.cmp_func = None

        for _attempt in range(3):
            err = vcli.vigem_target_add(self._busp, self._devicep)
            if err == vcom.VIGEM_ERRORS.VIGEM_ERROR_NONE.value:
                break
            if err == _PLUGGED_ERR:
                vcli.vigem_target_free(self._devicep)
                time.sleep(3)
                self._devicep = self.target_alloc()
            else:
                break

        assert vcli.vigem_target_is_attached(self._devicep), (
            "The virtual device could not connect to ViGEmBus."
        )

    vgmod.VGamepad.__init__ = _retrying_init  # type: ignore[assignment]


_patch_vgamepad_retry()


@dataclass
class _ControllerConfig:
    press_duration_ms: int = 100
    platform: Literal["auto", "linux", "windows"] = "windows"
    device_index: int = 0
    max_hold_ms: int = 5000
    max_sequence_steps: int = 20
    max_total_duration_ms: int = 10000


@dataclass
class _DiscordCfg:
    command_prefix: str = "!"
    channel_id: int = 0
    token: str = "tok"


@dataclass
class _QueueCfg:
    mode: Literal["fifo", "vote"] = "fifo"
    vote_window_seconds: float = 5.0
    fifo_execute_interval: float = 0.1
    max_depth: int = 50


@dataclass
class _RLCfg:
    cooldown_seconds: float = 1.0
    max_per_window: int = 3
    global_max_per_minute: int = 60


@dataclass
class _Cfg:
    discord: _DiscordCfg = None  # type: ignore
    queue: _QueueCfg = None  # type: ignore
    rate_limit: _RLCfg = None  # type: ignore
    controller: _ControllerConfig = None  # type: ignore

    def __post_init__(self) -> None:
        if self.discord is None:
            self.discord = _DiscordCfg()
        if self.queue is None:
            self.queue = _QueueCfg()
        if self.rate_limit is None:
            self.rate_limit = _RLCfg()
        if self.controller is None:
            self.controller = _ControllerConfig()


@pytest.fixture
def config():
    return _Cfg()


@pytest.fixture
def controller_config():
    return _ControllerConfig()


@pytest.fixture
async def controller(config):
    from controller.windows import WindowsController

    ctrl = WindowsController(config)
    yield ctrl
    await ctrl.cleanup()
