"""Pure configuration/back-end helpers for Kvaser (python-can) connections.

Kept free of top-level ``can``/``paramiko`` imports so the parsing logic can be
unit-tested without the hardware backends installed. The python-can module is
passed in (or imported lazily) by the few functions that need it.
"""

from __future__ import annotations

import ast
from typing import Any


def parse_kvaser_kwargs(raw: str) -> dict[str, Any]:
    text = (raw or "").strip()
    if not text:
        return {}

    result: dict[str, Any] = {}
    for chunk in text.split(","):
        part = chunk.strip()
        if not part:
            continue
        if "=" not in part:
            raise ValueError(f"Invalid extra parameter '{part}'. Use key=value format.")
        key, value = part.split("=", 1)
        key = key.strip()
        if not key:
            raise ValueError("Extra parameter keys cannot be empty.")
        result[key] = _coerce_scalar(value.strip())
    return result


def _coerce_scalar(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (int, float, bool)):
        return value

    text = str(value).strip()
    if text == "":
        return ""

    lowered = text.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    if lowered == "none":
        return None

    try:
        return ast.literal_eval(text)
    except Exception:
        return text


def _build_kvaser_bus_kwargs(
    *,
    interface: str,
    channel: Any,
    bitrate: int | None,
    extra_kwargs: dict[str, Any],
) -> dict[str, Any]:
    bus_kwargs: dict[str, Any] = {"interface": interface}
    if channel != "":
        bus_kwargs["channel"] = channel
    if bitrate is not None:
        bus_kwargs["bitrate"] = bitrate
    # Kvaser's canlib opens separate read/write handles by default and does
    # NOT echo a handle's own transmissions back to its own recv() unless
    # asked -- without this, CAN Send's Kvaser sends would be invisible in
    # this app's own receive stream (unlike SSH, where candump sees cansend's
    # traffic for free via SocketCAN). A standard python-can BusABC kwarg,
    # harmless for other backends; extra_kwargs below can still override it.
    bus_kwargs["receive_own_messages"] = True
    bus_kwargs.update(extra_kwargs)
    return bus_kwargs


def bitrate_probe_order(bitrates: list, *, priority: tuple = (250000, 500000)) -> list:
    """Reorder *bitrates* so the values in *priority* come first (in that
    order), then the rest in their original relative order."""
    seen = set()
    ordered = []
    for p in priority:
        if p in bitrates and p not in seen:
            ordered.append(p)
            seen.add(p)
    for b in bitrates:
        if b not in seen:
            ordered.append(b)
            seen.add(b)
    return ordered


def _is_kvaser_backend(interface: str) -> bool:
    return interface.strip().lower() == "kvaser"


def _is_virtual_kvaser_config(cfg: Any) -> bool:
    device_name = str(cfg.get("device_name", "")).strip().lower()
    serial = cfg.get("serial", None)
    return "virtual" in device_name or serial in {0, "0"}


def _validate_kvaser_channel_available(can_module, channel: Any) -> None:
    try:
        available = can_module.detect_available_configs(interfaces=["kvaser"])
    except Exception:
        # If detection is unavailable, keep python-can default behavior.
        return

    if not available:
        raise RuntimeError("No Kvaser device detected on this system.")

    physical_available = [cfg for cfg in available if not _is_virtual_kvaser_config(cfg)]
    if not physical_available:
        raise RuntimeError("No physical Kvaser device detected (only virtual channels are available).")

    normalized_channel = str(channel).strip() if channel is not None else ""
    if normalized_channel == "":
        return

    available_channels = {
        str(cfg.get("channel")).strip()
        for cfg in physical_available
        if cfg.get("channel") is not None and str(cfg.get("channel")).strip() != ""
    }

    if available_channels and normalized_channel not in available_channels:
        listed = ", ".join(sorted(available_channels))
        raise RuntimeError(
            f"Kvaser channel '{normalized_channel}' is not available. Detected channels: {listed}."
        )


def _patch_kvaser_linux_local_txecho(can_module) -> None:
    try:
        from can.interfaces.kvaser import canlib
    except Exception:
        return

    if getattr(canlib, "_canlytics_linux_txecho_patch", False):
        return

    original_can_ioctl_init = canlib.canIoCtlInit
    original_can_set_acceptance_filter = canlib.canSetAcceptanceFilter
    local_txecho = canlib.canstat.canIOCTL_SET_LOCAL_TXECHO
    local_txack = canlib.canstat.canIOCTL_SET_LOCAL_TXACK

    def can_ioctl_init_linux(handle, func, buf, buflen):
        try:
            return original_can_ioctl_init(handle, func, buf, buflen)
        except canlib.CanError as exc:
            error_code = getattr(exc, "error_code", None)
            # Linux Kvaser driver may reject local TX echo setup even when RX works.
            if func in {local_txecho, local_txack} and (
                error_code == -1 or "Error Code -1" in str(exc)
            ):
                return 0
            raise

    def can_set_acceptance_filter_linux(handle, code, mask, extended):
        try:
            return original_can_set_acceptance_filter(handle, code, mask, extended)
        except canlib.CanError as exc:
            error_code = getattr(exc, "error_code", None)
            # Some Linux Kvaser backends do not implement hardware acceptance filters.
            if error_code == -32 or "Error Code -32" in str(exc):
                return 0
            raise

    canlib.canIoCtlInit = can_ioctl_init_linux
    canlib.canSetAcceptanceFilter = can_set_acceptance_filter_linux
    canlib._canlytics_linux_txecho_patch = True
