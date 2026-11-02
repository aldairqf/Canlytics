from __future__ import annotations

import json
import math
import os
import tempfile
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import polars as pl

from services.can_data_parser import empty_frame
from services.can_log import CANLog
from services.candidate_interpretations import CandidateItem, build_candidate_items
from services.constraint_search import Constraint, search_candidates
from services.log_export import export_dataframe, select_export_frames
from services.range_diff import TimeRange, build_range_diff_report


class CanlyticsTools:
    """Process-local log state and safe operations exposed by MCP."""

    def __init__(
        self,
        *,
        output_dir: str | Path | None = None,
        allow_can_send: bool = False,
        tx_log_path: str | Path | None = None,
    ) -> None:
        self.dataframe = empty_frame()
        self.source_path: Path | None = None
        self.output_dir = Path(output_dir or Path.home() / ".canlytics" / "mcp").expanduser().resolve()
        self.allow_can_send = bool(allow_can_send)
        self.tx_log_path = Path(tx_log_path or self.output_dir / "tx-log.jsonl").expanduser().resolve()

    def load_log(self, path: str, normalize_time: bool = False) -> dict[str, Any]:
        """Load a source log read-only and replace the process-local session."""
        source = Path(path).expanduser().resolve(strict=True)
        if not source.is_file():
            raise ValueError("Log path must point to a file")
        dataframe = CANLog(source).load(normalize_time=normalize_time)
        self.dataframe = dataframe
        self.source_path = source
        return self._log_summary()

    def list_ids(self) -> list[str]:
        """List normalized CAN IDs in the loaded log."""
        self._require_log()
        return sorted(set(self.dataframe.get_column("ID").to_list()), key=lambda value: int(value, 16))

    def id_stats(self, can_id: str) -> dict[str, Any]:
        """Return frame count, observed lengths, buses and time bounds for one ID."""
        self._require_log()
        normalized = self._normalize_id(can_id)
        rows = self.dataframe.filter(pl.col("ID") == normalized)
        if rows.is_empty():
            raise ValueError(f"CAN ID {normalized} is not present in the loaded log")
        return {
            "can_id": normalized,
            "frames": rows.height,
            "lengths": sorted(set(int(value) for value in rows.get_column("LEN").to_list())),
            "buses": sorted(set(str(value) for value in rows.get_column("Bus").to_list())),
            "ts_min": float(rows.get_column("TS").min()),
            "ts_max": float(rows.get_column("TS").max()),
        }

    def find_candidates(
        self,
        can_ids: list[str] | None = None,
        min_length: int = 8,
        max_length: int = 8,
        granularity: int = 8,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Find signal interpretations for selected IDs using current candidate analysis."""
        self._require_log()
        if not 1 <= int(limit) <= 1000:
            raise ValueError("limit must be between 1 and 1000")
        min_length = max(1, min(int(min_length), 64))
        max_length = max(1, min(int(max_length), 64))
        if max_length < min_length:
            min_length, max_length = max_length, min_length
        ids = self._selected_ids(can_ids)
        items = build_candidate_items(
            self.dataframe,
            checked_ids=ids,
            mux_configs=[],
            min_length=min_length,
            max_length=max_length,
            granularity=max(1, min(int(granularity), 64)),
            endianness="Try Both",
            value_type="Try All",
            include_constant=False,
        )
        return [self._candidate_dict(item) for item in items[: int(limit)]]

    def diff_ranges(self, start_a: float, end_a: float, start_b: float, end_b: float) -> dict[str, Any]:
        """Compare two inclusive time ranges in the loaded log."""
        self._require_log()
        ranges = (float(start_a), float(end_a), float(start_b), float(end_b))
        if not all(math.isfinite(value) for value in ranges):
            raise ValueError("Range timestamps must be finite")
        start_a, end_a, start_b, end_b = ranges
        if start_a > end_a or start_b > end_b:
            raise ValueError("Each range start must be less than or equal to its end")
        report = build_range_diff_report(
            self.dataframe, TimeRange(float(start_a), float(end_a)), TimeRange(float(start_b), float(end_b)),
        )
        return {
            "range_a": asdict(report.range_a),
            "range_b": asdict(report.range_b),
            "ids": [asdict(item) for item in report.ids],
        }

    def constraint_search(
        self,
        constraints: list[dict[str, float]],
        can_ids: list[str] | None = None,
        precision: float = 0.1,
        tolerance: float = 0.1,
        limit: int = 100,
    ) -> dict[str, Any]:
        """Search candidate signals for normalized values near absolute timestamps."""
        self._require_log()
        if not constraints:
            raise ValueError("At least one time/value constraint is required")
        if not 1 <= int(limit) <= 1000:
            raise ValueError("limit must be between 1 and 1000")
        for item in constraints:
            if not isinstance(item, dict):
                raise ValueError("Each constraint must be an object")
            time_abs = float(item["time_abs"])
            target_norm = float(item["target_norm"])
            if not math.isfinite(time_abs) or not math.isfinite(target_norm) or not 0.0 <= target_norm <= 1.0:
                raise ValueError("Constraint timestamps must be finite and target_norm must be between 0 and 1")
        precision = float(precision)
        tolerance = float(tolerance)
        if not math.isfinite(precision) or precision < 0.0:
            raise ValueError("precision must be a finite non-negative number")
        if not math.isfinite(tolerance) or not 0.0 <= tolerance <= 1.0:
            raise ValueError("tolerance must be between 0 and 1")
        # Preserve the domain CandidateItem objects for the existing search service.
        ids = self._selected_ids(can_ids)
        items = build_candidate_items(
            self.dataframe,
            checked_ids=ids,
            mux_configs=[],
            min_length=8,
            max_length=8,
            granularity=8,
            endianness="Try Both",
            value_type="Try All",
            include_constant=False,
        )
        constraint_items = [
            Constraint(time_abs=float(item["time_abs"]), target_norm=float(item["target_norm"]))
            for item in constraints
        ]
        hits, exclusions = search_candidates(
            items, constraint_items, precision=precision, tolerance=tolerance,
        )
        return {
            "results": [
                {
                    "candidate": self._candidate_dict(result.item),
                    "hits": [asdict(hit) for hit in result.hits],
                }
                for result in hits[: max(0, int(limit))]
            ],
            "exclusions": asdict(exclusions),
        }

    def export_log(
        self,
        filename: str,
        scope: str = "all",
        can_ids: list[str] | None = None,
        ts_min: float | None = None,
        ts_max: float | None = None,
    ) -> dict[str, Any]:
        """Export a standard CAN log under the MCP output directory."""
        self._require_log()
        target = self._output_path(filename)
        if ts_min is not None and not math.isfinite(float(ts_min)):
            raise ValueError("ts_min must be finite")
        if ts_max is not None and not math.isfinite(float(ts_max)):
            raise ValueError("ts_max must be finite")
        if ts_min is not None and ts_max is not None and ts_min > ts_max:
            raise ValueError("ts_min must be less than or equal to ts_max")
        selected_ids: set[str] = set()
        if scope == "filtered":
            if not can_ids:
                raise ValueError("can_ids is required for filtered export")
            selected_ids = self._selected_ids(can_ids)
        dataframe = select_export_frames(
            self.dataframe, scope, selected_ids=selected_ids, ts_min=ts_min, ts_max=ts_max,
        )
        target.parent.mkdir(parents=True, exist_ok=True)
        exported = export_dataframe(
            dataframe, target, protected_paths=[self.source_path] if self.source_path else (),
        )
        return {"path": str(exported), "frames": dataframe.height}

    def save_signals(self, filename: str, signals: list[dict[str, Any]]) -> dict[str, Any]:
        """Save user-provided signal definitions as JSON outside source log folders."""
        self._require_json_filename(filename)
        if not signals or any(not isinstance(signal, dict) for signal in signals):
            raise ValueError("signals must be a non-empty list of objects")
        path = self._write_json(filename, {"signals": signals})
        return {"path": str(path), "signals": len(signals)}

    def save_markers(self, filename: str, markers: list[dict[str, Any]]) -> dict[str, Any]:
        """Save named timestamp markers as JSON outside source log folders."""
        self._require_json_filename(filename)
        for marker in markers:
            if not isinstance(marker, dict) or not isinstance(marker.get("name"), str):
                raise ValueError("Each marker needs a string name and timestamp")
            if not isinstance(marker.get("timestamp"), (int, float)):
                raise ValueError("Each marker needs a numeric timestamp")
            if not math.isfinite(float(marker["timestamp"])):
                raise ValueError("Marker timestamps must be finite")
        path = self._write_json(filename, {"markers": markers})
        return {"path": str(path), "markers": len(markers)}

    def send_frame(
        self,
        channel: str,
        can_id: int,
        data_hex: str,
        interface: str = "socketcan",
        extended: bool = False,
    ) -> dict[str, Any]:
        """Send one frame when explicitly enabled and append every attempt to TX log."""
        if not self.allow_can_send:
            raise PermissionError("CAN transmit is disabled; restart with --allow-can-send")
        if self.source_path and self.tx_log_path == self.source_path:
            raise PermissionError("TX log cannot overwrite the loaded source log")
        arbitration_id = int(can_id)
        payload = bytes.fromhex(data_hex)
        if not 0 <= arbitration_id <= 0x1FFFFFFF or len(payload) > 8:
            raise ValueError("CAN ID or classic CAN payload is out of range")
        record: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "interface": interface,
            "channel": channel,
            "can_id": f"{arbitration_id:X}",
            "data": payload.hex().upper(),
            "status": "error",
        }
        bus = None
        try:
            import can

            bus = can.Bus(interface=interface, channel=channel)
            bus.send(can.Message(
                arbitration_id=arbitration_id,
                data=payload,
                is_extended_id=bool(extended),
            ), timeout=1.0)
            record["status"] = "sent"
            return {key: value for key, value in record.items() if key != "timestamp"}
        except Exception as exc:
            record["error"] = str(exc)
            raise
        finally:
            try:
                if bus is not None:
                    bus.shutdown()
            finally:
                self._append_tx_record(record)

    def _log_summary(self) -> dict[str, Any]:
        if self.dataframe.is_empty():
            return {"path": str(self.source_path), "frames": 0, "ids": 0}
        return {
            "path": str(self.source_path),
            "frames": self.dataframe.height,
            "ids": len(self.list_ids()),
            "ts_min": float(self.dataframe.get_column("TS").min()),
            "ts_max": float(self.dataframe.get_column("TS").max()),
        }

    def _require_log(self) -> None:
        if self.source_path is None:
            raise RuntimeError("Call load_log before using log analysis tools")

    def _selected_ids(self, can_ids: list[str] | None) -> set[str]:
        ids = {self._normalize_id(value) for value in can_ids} if can_ids else set(self.list_ids())
        unknown = ids - set(self.list_ids())
        if unknown:
            raise ValueError(f"CAN IDs are not present in the loaded log: {sorted(unknown)}")
        return ids

    @staticmethod
    def _normalize_id(value: str) -> str:
        text = str(value).strip().upper().removeprefix("0X")
        if not text or any(char not in "0123456789ABCDEF" for char in text):
            raise ValueError(f"Invalid hexadecimal CAN ID: {value}")
        return f"{int(text, 16):X}"

    @staticmethod
    def _candidate_dict(item: CandidateItem) -> dict[str, Any]:
        return {
            "label": item.label,
            "can_id": item.can_id,
            "frame_len": item.frame_len,
            "start_bit": item.start_bit,
            "signal_length": item.signal_length,
            "byte_order": item.byte_order,
            "value_type": item.value_type,
            "frames": item.frames,
            "changes": item.changes,
            "score": item.score,
            "min_value": item.min_value,
            "max_value": item.max_value,
            "sample_values": list(item.sample_values),
        }

    def _output_path(self, filename: str) -> Path:
        relative = Path(filename)
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("Output filenames must stay inside the MCP output directory")
        target = (self.output_dir / relative).resolve()
        if not target.is_relative_to(self.output_dir):
            raise ValueError("Output path escapes the MCP output directory")
        if self.source_path and target == self.source_path:
            raise ValueError("The loaded source log is read-only")
        if target == self.tx_log_path:
            raise ValueError("The TX audit log is reserved and cannot be replaced")
        return target

    @staticmethod
    def _require_json_filename(filename: str) -> None:
        if Path(filename).suffix.lower() != ".json":
            raise ValueError("Signal and marker artifacts must use the .json extension")

    def _write_json(self, filename: str, payload: dict[str, Any]) -> Path:
        target = self._output_path(filename)
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary_name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2, allow_nan=False)
                handle.write("\n")
            os.replace(temporary_name, target)
        except BaseException:
            Path(temporary_name).unlink(missing_ok=True)
            raise
        return target

    def _append_tx_record(self, record: dict[str, Any]) -> None:
        if not self.tx_log_path.is_relative_to(self.output_dir):
            raise ValueError("TX log must stay inside the MCP output directory")
        self.tx_log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.tx_log_path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, allow_nan=False) + "\n")
