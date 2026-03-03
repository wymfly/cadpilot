"""G-code metadata parser.

Supports PrusaSlicer and OrcaSlicer comment formats.
Extracts: layer count, G1 instruction count, filament usage (mm/g),
and estimated print time.

On failure, returns an empty dict and logs a warning — G-code file
is still usable even if metadata extraction fails.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

# Patterns for metadata extraction
_RE_LAYERS = re.compile(r";\s*total layers count\s*=\s*(\d+)")
_RE_FILAMENT_MM = re.compile(r";\s*filament used \[mm\]\s*=\s*([\d.]+)")
_RE_FILAMENT_G = re.compile(r";\s*filament used \[g\]\s*=\s*([\d.]+)")

# PrusaSlicer: ; estimated printing time (normal mode) = 1h 30m 15s
_RE_PRINT_TIME_PRUSA = re.compile(
    r";\s*estimated printing time \(normal mode\)\s*=\s*(.+)"
)
# OrcaSlicer: ; total estimated time = 2h 15m 30s
_RE_PRINT_TIME_ORCA = re.compile(
    r";\s*total estimated time\s*=\s*(.+)"
)

_RE_G1 = re.compile(r"^G1\s", re.MULTILINE)


def parse_gcode_metadata(gcode_path: Path) -> dict:
    """Parse G-code file and extract metadata.

    Parameters
    ----------
    gcode_path:
        Path to the G-code file.

    Returns
    -------
    dict with keys: layers, g1_count, filament_used_mm, filament_used_g,
    print_time. Missing values are omitted. Returns empty dict on failure.
    """
    try:
        if not gcode_path.exists():
            logger.warning("G-code file not found: %s", gcode_path)
            return {}

        content = gcode_path.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:
        logger.warning("Failed to read G-code file %s: %s", gcode_path, exc)
        return {}

    meta: dict = {}

    try:
        # Layer count
        m = _RE_LAYERS.search(content)
        if m:
            meta["layers"] = int(m.group(1))

        # Filament usage (mm)
        m = _RE_FILAMENT_MM.search(content)
        if m:
            meta["filament_used_mm"] = float(m.group(1))

        # Filament usage (g)
        m = _RE_FILAMENT_G.search(content)
        if m:
            meta["filament_used_g"] = float(m.group(1))

        # Print time (try PrusaSlicer format first, then OrcaSlicer)
        m = _RE_PRINT_TIME_PRUSA.search(content)
        if m:
            meta["print_time"] = m.group(1).strip()
        else:
            m = _RE_PRINT_TIME_ORCA.search(content)
            if m:
                meta["print_time"] = m.group(1).strip()

        # G1 instruction count
        g1_matches = _RE_G1.findall(content)
        meta["g1_count"] = len(g1_matches)

    except Exception as exc:
        logger.warning("Failed to parse G-code metadata from %s: %s", gcode_path, exc)
        return {}

    return meta
