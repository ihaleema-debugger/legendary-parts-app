import json
from pathlib import Path
from typing import Optional

_LANES_PATH = Path(__file__).parent.parent / "config" / "lanes.json"


def load_parked_lanes(lanes_path: Optional[Path] = None) -> set:
    """Return the set of parked lane numbers from lanes.json.

    Raises FileNotFoundError (loudly) if the config file is missing — a missing
    file must not silently un-park lanes.
    """
    p = Path(lanes_path) if lanes_path else _LANES_PATH
    if not p.exists():
        raise FileNotFoundError(
            f"lanes.json not found at {p}. "
            "This file is required to enforce lane parking. "
            "Create it with at least {\"parked_lanes\": []} to un-park all lanes, "
            "or {\"parked_lanes\": [1]} to keep lane 1 parked."
        )
    with open(p, encoding="utf-8") as f:
        data = json.load(f)
    return set(data.get("parked_lanes", []))
