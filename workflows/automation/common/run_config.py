from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
import math
from typing import Any, Dict, List, Literal, Optional


ProgressionMode = Literal["time", "stability"]


@dataclass
class UnifiedStep:
    name: str
    bath_setpoint_c: float
    tec_power_w: float
    duration_s: float
    progression_mode: ProgressionMode = "time"
    stability_band_c: Optional[float] = None
    stability_hold_s: Optional[float] = None
    stability_timeout_s: Optional[float] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any], step_index: int) -> "UnifiedStep":
        required = ["name", "bath_setpoint_c", "tec_power_w", "duration_s"]
        missing = [key for key in required if key not in data]
        if missing:
            raise ValueError(f"Unified step {step_index} is missing required keys: {missing}")

        progression_mode = str(data.get("progression_mode", "time")).strip().lower()
        if progression_mode not in {"time", "stability"}:
            raise ValueError(
                f"Unified step {step_index} has invalid progression_mode={progression_mode!r}; expected 'time' or 'stability'"
            )

        legacy_nonzero_intent = bool(data.get("_legacy_nonzero_intent", False))
        step = cls(
            name=str(data["name"]),
            bath_setpoint_c=float(data["bath_setpoint_c"]),
            tec_power_w=float(data["tec_power_w"]),
            duration_s=float(data["duration_s"]),
            progression_mode=progression_mode,
            stability_band_c=_optional_float(data.get("stability_band_c")),
            stability_hold_s=_optional_float(data.get("stability_hold_s")),
            stability_timeout_s=_optional_float(data.get("stability_timeout_s")),
        )
        step.validate(step_index)
        setattr(step, "_legacy_nonzero_intent", legacy_nonzero_intent)
        return step

    def validate(self, step_index: int) -> None:
        if not self.name.strip():
            raise ValueError(f"Unified step {step_index} has an empty name")
        if not math.isfinite(self.duration_s) or self.duration_s <= 0.0:
            raise ValueError(f"Unified step {step_index} duration_s must be finite and > 0")
        if self.progression_mode == "stability":
            if self.stability_band_c is not None and (not math.isfinite(self.stability_band_c) or self.stability_band_c <= 0.0):
                raise ValueError(f"Unified step {step_index} stability_band_c must be finite and > 0 when provided")
            if self.stability_hold_s is not None and (not math.isfinite(self.stability_hold_s) or self.stability_hold_s <= 0.0):
                raise ValueError(f"Unified step {step_index} stability_hold_s must be finite and > 0 when provided")
            if self.stability_timeout_s is not None and (not math.isfinite(self.stability_timeout_s) or self.stability_timeout_s <= 0.0):
                raise ValueError(f"Unified step {step_index} stability_timeout_s must be finite and > 0 when provided")


@dataclass
class SafetyConfig:
    tec_power_w_on_stop: float = 0.0
    bath_standby_setpoint_c: float = 25.0
    pump_on_in_safe_state: bool = True

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SafetyConfig":
        cfg = cls(
            tec_power_w_on_stop=float(data.get("tec_power_w_on_stop", 0.0)),
            bath_standby_setpoint_c=float(data.get("bath_standby_setpoint_c", 25.0)),
            pump_on_in_safe_state=bool(data.get("pump_on_in_safe_state", True)),
        )
        if not math.isfinite(cfg.tec_power_w_on_stop):
            raise ValueError("safety.tec_power_w_on_stop must be finite")
        if not math.isfinite(cfg.bath_standby_setpoint_c):
            raise ValueError("safety.bath_standby_setpoint_c must be finite")
        return cfg


@dataclass
class RunConfig:
    run_name: Optional[str] = None
    steps: List[UnifiedStep] = field(default_factory=list)
    safety: SafetyConfig = field(default_factory=SafetyConfig)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RunConfig":
        payload = dict(data)
        raw_steps: List[Dict[str, Any]]
        if "steps" in payload:
            raw_steps = list(payload.get("steps") or [])
        elif "power_schedule" in payload:
            raw_steps = _map_tec_power_schedule_to_unified_steps(list(payload.get("power_schedule") or []))
        else:
            raise ValueError("Run config must include either 'steps' (unified) or 'power_schedule' (legacy TEC-only)")

        if not raw_steps:
            raise ValueError("Run config must include at least one step")

        steps = [UnifiedStep.from_dict(step, step_index=i) for i, step in enumerate(raw_steps)]
        safety = SafetyConfig.from_dict(dict(payload.get("safety") or {}))
        run_name = payload.get("run_name")
        run_name_text = str(run_name).strip() if run_name is not None else None
        return cls(run_name=run_name_text or None, steps=steps, safety=safety)

    @classmethod
    def from_json_file(cls, path: str | Path) -> "RunConfig":
        with open(path, "r", encoding="utf-8") as handle:
            content = json.load(handle)
        return cls.from_dict(content)


def _optional_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    return float(value)


def _map_tec_power_schedule_to_unified_steps(power_schedule: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    mapped: List[Dict[str, Any]] = []
    for idx, legacy in enumerate(power_schedule):
        name = str(legacy.get("name", f"step_{idx + 1}"))
        tec_power_w = float(legacy.get("power", 0.0) or 0.0)
        duration_s = float(legacy.get("duration_seconds", 0.0) or 0.0)
        mapped.append(
            {
                "name": name,
                "bath_setpoint_c": 25.0,
                "tec_power_w": tec_power_w,
                "duration_s": duration_s,
                "progression_mode": "time",
                "_legacy_nonzero_intent": bool((legacy.get("set_voltage") or 0) != 0 or (legacy.get("set_current") or 0) != 0),
            }
        )
    return mapped


def load_run_config_json(path: str | Path) -> RunConfig:
    """Load and validate a unified run configuration from a JSON file path."""
    return RunConfig.from_json_file(path)
