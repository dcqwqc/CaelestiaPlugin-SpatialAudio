#!/usr/bin/env python3
import json
from pathlib import Path

path = Path.home() / ".config/caelestia/plugins.json"
data = json.loads(path.read_text())
data.setdefault("enabled", [])
if "dcqwqc/spatialaudio" not in data["enabled"]:
    data["enabled"].append("dcqwqc/spatialaudio")

settings = data.setdefault("settings", {}).setdefault("dcqwqc/spatialaudio", {})
defaults = {
    "enabled": False,
    "mode": "Pan",
    "pan": 0,
    "elevation": 0,
    "width": 1,
    "intensity": 1,
    "movementMs": 220,
}
for key, value in defaults.items():
    settings.setdefault(key, value)

path.write_text(json.dumps(data, indent=4) + "\n")
