"""How much clearance a fit needs on this printer, and whether the parts have it.

A clearance is the gap per side between two mating surfaces, as modelled. The
defaults are the usual starting points for a 0.4 mm nozzle in PLA; printing the
fit coupon and recording what you feel replaces them with your printer's own.
Scripts read them as params["fit"], so a slide fit is
`params["fit"]["slide"]` rather than a number guessed per part.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from print3d.printability import Advice

FITS_ENV = "PRINT3D_FITS"
# Per side, in mm. press: hammered or pressed in, stays put. snug: pushes in by
# hand, holds. slide: moves without play. free: turns or drops in loosely.
DEFAULT_CLEARANCE_MM = {"press": 0.05, "snug": 0.10, "slide": 0.20, "free": 0.35}
KINDS = tuple(DEFAULT_CLEARANCE_MM)
# How far from the target a measured gap may sit before it is a different fit.
TIGHTER_BY_MM = 0.04
LOOSER_BY_MM = 0.10


def fits_path() -> Path:
    if env := os.environ.get(FITS_ENV, "").strip():
        return Path(env).expanduser()
    return Path.home() / "print3d" / "fits.json"


def load_fits() -> dict[str, Any]:
    path = fits_path()
    saved = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    clearance = {**DEFAULT_CLEARANCE_MM, **saved.get("clearance_mm", {})}
    calibrated = sorted(saved.get("clearance_mm", {}))
    return {
        "clearance_mm": clearance,
        "calibrated": calibrated,
        "calibrated_at": saved.get("calibrated_at"),
        "path": str(path),
    }


def save_fits(values: dict[str, float]) -> dict[str, Any]:
    unknown = sorted(set(values) - set(KINDS))
    if unknown:
        raise ValueError(f"Unknown fit {', '.join(unknown)}. Fits are: {', '.join(KINDS)}.")
    if any(mm < 0 or mm > 1.0 for mm in values.values()):
        raise ValueError("A clearance is per side, in mm, between 0 and 1.")
    path = fits_path()
    saved = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    clearance = {**saved.get("clearance_mm", {}), **{k: round(v, 3) for k, v in values.items()}}
    order = [clearance.get(kind) for kind in KINDS if kind in clearance]
    if order != sorted(order):
        raise ValueError(f"Fits must loosen in the order {' < '.join(KINDS)}; got {clearance}.")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"clearance_mm": clearance, "calibrated_at": time.strftime("%Y-%m-%d")}, indent=2) + "\n",
        encoding="utf-8",
    )
    return load_fits()


def _declared(pair: dict[str, Any], declared: list[dict[str, Any]]) -> str | None:
    for spec in declared:
        if {spec["a"], spec["b"]} == {pair["a"], pair["b"]}:
            return spec["kind"]
    return None


def fit_verdict(pair: dict[str, Any], kind: str | None, clearance: dict[str, float]) -> str:
    """interference, fused, unmeasured, tight, loose, ok; or clear for an undeclared pair that is fine."""
    if pair["interference_mm"] > 0:
        return "interference"
    gap = pair["clearance_mm"]
    if gap is None and pair["contact"]:
        gap = 0.0 if kind else None
    if kind is None:
        return "fused" if gap is not None and gap < clearance["press"] - TIGHTER_BY_MM / 2 else "clear"
    if gap is None:
        return "unmeasured"
    if gap < clearance[kind] - TIGHTER_BY_MM:
        return "tight"
    if gap > clearance[kind] + LOOSER_BY_MM:
        return "loose"
    return "ok"


def fit_advice(
    pairs: list[dict[str, Any]], declared: list[dict[str, Any]], clearance: dict[str, float]
) -> list[Advice]:
    """Interference is an error; a declared fit outside its clearance is a warning.

    Each pair gains `declared` and `verdict`.
    """
    notes: list[Advice] = []
    for pair in pairs:
        kind = pair["declared"] = _declared(pair, declared)
        verdict = pair["verdict"] = fit_verdict(pair, kind, clearance)
        names = f"{pair['a']} and {pair['b']}"
        gap = pair["clearance_mm"] or 0.0
        target = clearance[kind or "slide"]
        if verdict == "interference":
            notes.append(
                Advice(
                    "interference",
                    "error",
                    f"{names} overlap by {pair['interference_mm']:.2f} mm as assembled: "
                    "they will not go together.",
                    f"Cut one back so they clear by params['fit']['{kind or 'slide'}'] "
                    f"({target:.2f} mm per side).",
                    part=pair["a"],
                )
            )
        elif verdict == "fused":
            notes.append(
                Advice(
                    "fused",
                    "warn",
                    f"{names} are {gap:.2f} mm apart: too close to print as separate "
                    "surfaces, too far to touch.",
                    "Make them touch, or open the gap to a fit from params['fit'] and declare it with fit().",
                    part=pair["a"],
                )
            )
        elif verdict == "unmeasured":
            notes.append(
                Advice(
                    "fit",
                    "warn",
                    f"{names} are declared a {kind} fit but no gap under 2 mm separates them.",
                    "Model the parts where they sit when assembled, so the fit can be measured.",
                    part=pair["a"],
                )
            )
        elif verdict in ("tight", "loose"):
            notes.append(
                Advice(
                    "fit",
                    "warn",
                    f"{names}: {gap:.2f} mm per side is {verdict}er than a {kind} fit "
                    f"({target:.2f} mm on this printer)"
                    + (" and will rattle." if verdict == "loose" else "."),
                    f"{'Open' if verdict == 'tight' else 'Close'} the gap to params['fit']['{kind}'].",
                    part=pair["a"],
                )
            )
    for spec in declared:
        if not any({spec["a"], spec["b"]} == {p["a"], p["b"]} for p in pairs):
            notes.append(
                Advice(
                    "fit",
                    "warn",
                    f"{spec['a']} and {spec['b']} are declared a {spec['kind']} fit but never "
                    "come within 2 mm of each other.",
                    "Model the parts where they sit when assembled, so the fit can be measured.",
                    part=spec["a"],
                )
            )
    return notes
