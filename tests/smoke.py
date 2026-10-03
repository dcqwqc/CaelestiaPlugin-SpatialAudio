#!/usr/bin/env python3
"""Real, silent PipeWire lifecycle smoke test. Run explicitly: tests/smoke.py --real."""
import importlib.util, json, pathlib, subprocess, sys, time

ROOT = pathlib.Path(__file__).resolve().parents[1]
HELPER = ROOT / "scripts/spatial-audio-controller.py"
if "--real" not in sys.argv:
    print("Refusing live routing change without --real")
    raise SystemExit(0)
spec = importlib.util.spec_from_file_location("controller", HELPER)
ctl = importlib.util.module_from_spec(spec); spec.loader.exec_module(ctl)
before = ctl.default_name()
try:
    expected_restore = json.loads(ctl.STATE.read_text()).get("prior_default") if before == ctl.VIRTUAL else before
except (OSError, json.JSONDecodeError):
    expected_restore = before
saved = ctl.config()
def configure(values):
    subprocess.run([str(HELPER), "configure", json.dumps(values)], check=True)
    time.sleep(1)
def status(): return json.loads(subprocess.check_output([str(HELPER), "status"], text=True))
try:
    configure({**saved, "enabled": True, "mode": "Pan", "pan": -.4})
    assert status()["active"] and status()["virtual"] == ctl.VIRTUAL
    configure({**saved, "enabled": True, "mode": "HRTF", "pan": .3, "elevation": 10})
    assert status()["active"] and status()["mode"] == "HRTF" and status()["sofa"]
    configure({**saved, "enabled": False})
    assert ctl.default_name() == expected_restore, (ctl.default_name(), expected_restore)
finally:
    configure(saved)
print("silent create/change/teardown/restore smoke passed")
