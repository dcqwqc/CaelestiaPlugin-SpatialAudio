#!/usr/bin/env python3
"""PipeWire owner/controller for the Caelestia Spatial Audio plugin."""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

APP = "caelestia-spatial-audio"
VIRTUAL = "caelestia_spatial_audio"
ROOT = Path(__file__).resolve().parents[1]
SOFA = Path("/usr/share/libmysofa/MIT_KEMAR_normal_pinna.sofa")
SOFA_PLUGIN = Path("/usr/lib/spa-0.2/filter-graph/libspa-filter-graph-plugin-sofa.so")
CONFIG = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / APP / "config.json"
STATE = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state")) / APP / "state.json"
RUNTIME = Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp")) / APP / "status.json"

DEFAULT = {
    "enabled": False,
    "mode": "Pan",
    "pan": 0.0,
    "elevation": 0.0,
    "width": 1.0,
    "intensity": 1.0,
    "movement_ms": 220,
}


def atomic(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".new")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    tmp.replace(path)


def config() -> dict:
    try:
        raw = json.loads(CONFIG.read_text())
    except (OSError, json.JSONDecodeError):
        raw = {}
    cfg = DEFAULT | {k: raw[k] for k in DEFAULT if k in raw}
    cfg["mode"] = "HRTF" if str(cfg["mode"]).upper() == "HRTF" else "Pan"
    for key, lo, hi in (
        ("pan", -1.0, 1.0),
        ("elevation", -45.0, 45.0),
        ("width", 0.0, 1.0),
        ("intensity", 0.0, 1.0),
        ("movement_ms", 20, 2000),
    ):
        try:
            cfg[key] = max(lo, min(hi, float(cfg[key])))
        except (TypeError, ValueError):
            cfg[key] = DEFAULT[key]
    cfg["movement_ms"] = int(cfg["movement_ms"])
    cfg["enabled"] = bool(cfg["enabled"])
    return cfg


def read_state() -> dict:
    try:
        return json.loads(STATE.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def dump() -> list:
    return json.loads(subprocess.check_output(["pw-dump"], text=True))


def props(node: dict) -> dict:
    return node.get("info", {}).get("props", {})


def nodes() -> list:
    return [n for n in dump() if n.get("type") == "PipeWire:Interface:Node"]


def default_name() -> str | None:
    result = subprocess.run(
        ["wpctl", "inspect", "@DEFAULT_AUDIO_SINK@"],
        text=True,
        capture_output=True,
    )
    for line in result.stdout.splitlines():
        if "node.name" in line and "=" in line:
            return line.split("=", 1)[1].strip().strip('"')
    return None


def physical_sink() -> dict | None:
    candidates = [
        n
        for n in nodes()
        if props(n).get("media.class") == "Audio/Sink"
        and not props(n).get("node.name", "").startswith(VIRTUAL)
    ]
    if not candidates:
        return None

    current = default_name()
    if current and not current.startswith(VIRTUAL):
        match = next((n for n in candidates if props(n).get("node.name") == current), None)
        if match:
            return match

    remembered = read_state()
    for key in ("physical", "prior_default"):
        name = remembered.get(key)
        match = next((n for n in candidates if props(n).get("node.name") == name), None)
        if match:
            return match

    speaker = next(
        (
            n for n in candidates
            if "speaker" in (
                props(n).get("node.description", "") + " "
                + props(n).get("node.name", "")
            ).lower()
            and "hdmi" not in (
                props(n).get("node.description", "") + " "
                + props(n).get("node.name", "")
            ).lower()
        ),
        None,
    )
    return speaker or candidates[0]


def node_id(name: str) -> int | None:
    try:
        return next(int(n["id"]) for n in nodes() if props(n).get("node.name") == name)
    except (StopIteration, subprocess.SubprocessError, json.JSONDecodeError):
        return None


def q(value: str) -> str:
    return json.dumps(value)


def hrtf_available() -> bool:
    return SOFA.is_file() and SOFA_PLUGIN.is_file()


def hrtf_azimuth(pan: float) -> float:
    # SOFA: 0 front, 90 left, 180 back, 270 right.
    return (-float(pan) * 90.0) % 360.0


def graph(cfg: dict, physical: str) -> str:
    if cfg["mode"] == "Pan":
        return f'''{{ node.description = "Caelestia Spatial Audio (Pan)"
filter.graph = {{
  nodes = [ {{ type = builtin name = copy label = copy }} ]
  inputs = [ "copy:In L" "copy:In R" ]
  outputs = [ "copy:Out L" "copy:Out R" ]
}}
audio.channels = 2
audio.position = [ FL FR ]
capture.props = {{
  node.name = {q(VIRTUAL)}
  media.class = Audio/Sink
  node.virtual = true
}}
playback.props = {{
  node.name = {q(VIRTUAL + "_raw")}
  node.passive = true
  node.dont-reconnect = true
  target.object = 0
}}
}}'''

    return f'''{{ node.description = "Caelestia Spatial Audio (HRTF)"
filter.graph = {{
  nodes = [
    {{
      type = sofa
      name = hrtf
      label = spatializer
      config = {{
        filename = {q(str(SOFA))}
        normalize = true
      }}
      control = {{
        "Azimuth" = {hrtf_azimuth(cfg["pan"]):.4f}
        "Elevation" = {cfg["elevation"]:.4f}
        "Radius" = 3.0
      }}
    }}
  ]
  inputs = [ "hrtf:In" ]
  outputs = [ "hrtf:Out L" "hrtf:Out R" ]
}}
audio.channels = 1
audio.position = [ MONO ]
capture.props = {{
  node.name = {q(VIRTUAL)}
  media.class = Audio/Sink
  node.virtual = true
}}
playback.props = {{
  node.name = {q(VIRTUAL + "_hrtf")}
  node.passive = true
  node.dont-reconnect = true
  target.object = {q(physical)}
  audio.channels = 2
  audio.position = [ FL FR ]
}}
}}'''



class Runtime:
    def __init__(self) -> None:
        self.cli = None
        self.rec = None
        self.dsp = None
        self.play = None
        self.vid: int | None = None
        self.mode: str | None = None
        self.physical: str | None = None
        self.last_error: str | None = None
        self.current_hrtf = [0.0, 0.0, 1.0]
        self.start_hrtf = [0.0, 0.0, 1.0]
        self.target_hrtf = [0.0, 0.0, 1.0]
        self.move_started = 0.0
        self.move_duration = 0.22

    def terminate(self) -> None:
        for proc in (self.rec, self.dsp, self.play, self.cli):
            if proc and proc.poll() is None:
                proc.terminate()
        for proc in (self.rec, self.dsp, self.play, self.cli):
            if not proc:
                continue
            try:
                proc.wait(timeout=1.2)
            except subprocess.TimeoutExpired:
                proc.kill()
                try:
                    proc.wait(timeout=0.5)
                except subprocess.TimeoutExpired:
                    pass
        self.cli = self.rec = self.dsp = self.play = None
        self.vid = None
        self.mode = None
        self.physical = None

    def _command(self, line: str) -> bool:
        if not self.cli or self.cli.poll() is not None or not self.cli.stdin:
            return False
        try:
            self.cli.stdin.write(line.rstrip() + "\n")
            self.cli.stdin.flush()
            return True
        except (BrokenPipeError, OSError):
            return False

    def start(self, cfg: dict, physical_node: dict) -> bool:
        name = props(physical_node).get("node.name")
        if not name or name.startswith(VIRTUAL):
            self.last_error = "No safe physical sink"
            return False
        if cfg["mode"] == "HRTF" and not hrtf_available():
            self.last_error = "SOFA backend unavailable"
            return False

        self.cli = subprocess.Popen(
            ["pw-cli"],
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        graph_args = " ".join(graph(cfg, name).splitlines())
        if not self._command("load-module libpipewire-module-filter-chain " + graph_args):
            self.last_error = "Could not submit filter graph"
            self.terminate()
            return False

        for _ in range(50):
            self.vid = node_id(VIRTUAL)
            if self.vid is not None:
                break
            if self.cli.poll() is not None:
                break
            time.sleep(0.04)
        if self.vid is None:
            self.last_error = "Virtual sink did not appear"
            self.terminate()
            return False

        subprocess.run(
            ["wpctl", "set-default", str(self.vid)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        self.mode = cfg["mode"]
        self.physical = name

        if self.mode == "Pan":
            dspbin = ROOT / "native/spatial-dsp"
            if not dspbin.is_file():
                self.last_error = "Pan DSP binary missing"
                self.terminate()
                return False

            self.rec = subprocess.Popen(
                [
                    "pw-cat", "--record", "--raw", "--format", "f32",
                    "--rate", "48000", "--channels", "2",
                    "--channel-map", "FL,FR",
                    "--target", VIRTUAL,
                    "-P", "node.name=caelestia_spatial_audio_capture",
                    "-",
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )
            self.dsp = subprocess.Popen(
                [str(dspbin), str(CONFIG)],
                stdin=self.rec.stdout,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )
            if self.rec.stdout:
                self.rec.stdout.close()

            self.play = subprocess.Popen(
                [
                    "pw-cat", "--playback", "--raw", "--format", "f32",
                    "--rate", "48000", "--channels", "2",
                    "--channel-map", "FL,FR",
                    "--target", name,
                    "-P", "node.name=caelestia_spatial_audio_playback,node.dont-reconnect=true",
                    "-",
                ],
                stdin=self.dsp.stdout,
                stderr=subprocess.DEVNULL,
            )
            if self.dsp.stdout:
                self.dsp.stdout.close()

            time.sleep(0.18)
            if not self.healthy(check_node=False):
                self.last_error = "Pan capture/DSP/playback pipeline exited"
                self.terminate()
                return False
        else:
            self.current_hrtf = [cfg["pan"], cfg["elevation"], cfg["intensity"]]
            self.start_hrtf = self.current_hrtf.copy()
            self.target_hrtf = self.current_hrtf.copy()
            self.move_started = time.monotonic()
            self.move_duration = max(0.02, cfg["movement_ms"] / 1000.0)
            if not self._send_hrtf(*self.current_hrtf):
                self.last_error = "Could not set HRTF controls"
                self.terminate()
                return False

        self.last_error = None
        return True

    def healthy(self, check_node: bool = True) -> bool:
        if not self.cli or self.cli.poll() is not None or self.vid is None:
            return False
        if self.mode == "Pan":
            if any(
                proc is None or proc.poll() is not None
                for proc in (self.rec, self.dsp, self.play)
            ):
                return False
        if check_node and node_id(VIRTUAL) != self.vid:
            return False
        return True

    def set_hrtf_target(self, cfg: dict) -> None:
        if self.mode != "HRTF":
            return
        target = [cfg["pan"], cfg["elevation"], cfg["intensity"]]
        if all(abs(a - b) < 1e-6 for a, b in zip(target, self.target_hrtf)):
            return
        self.start_hrtf = self.current_hrtf.copy()
        self.target_hrtf = target
        self.move_started = time.monotonic()
        self.move_duration = max(0.02, cfg["movement_ms"] / 1000.0)

    def _send_hrtf(self, pan: float, elevation: float, intensity: float) -> bool:
        if self.vid is None:
            return False
        payload = (
            '{ volume = %.6f params = [ "hrtf:Azimuth" %.6f '
            '"hrtf:Elevation" %.6f "hrtf:Radius" 3.0 ] }'
            % (intensity, hrtf_azimuth(pan), elevation)
        )
        return self._command(f"set-param {self.vid} Props {payload}")

    def tick_hrtf(self) -> None:
        if self.mode != "HRTF" or not self.healthy(check_node=False):
            return
        elapsed = time.monotonic() - self.move_started
        t = min(1.0, elapsed / self.move_duration)
        ease = t * t * (3.0 - 2.0 * t)
        values = [
            a + (b - a) * ease
            for a, b in zip(self.start_hrtf, self.target_hrtf)
        ]
        if (
            any(abs(a - b) > 1e-4 for a, b in zip(values, self.current_hrtf))
            or t >= 1.0
        ):
            self.current_hrtf = values
            self._send_hrtf(*values)


def restore_default() -> None:
    remembered = read_state()
    for name in (remembered.get("prior_default"), remembered.get("physical")):
        if not name or name.startswith(VIRTUAL):
            continue
        ident = node_id(name)
        if ident is not None:
            subprocess.run(
                ["wpctl", "set-default", str(ident)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            break
    RUNTIME.unlink(missing_ok=True)


def runtime_status(
    runtime: Runtime, cfg: dict, active: bool, reason: str | None = None
) -> None:
    atomic(
        RUNTIME,
        {
            "active": bool(active),
            "mode": runtime.mode or cfg["mode"],
            "physical": runtime.physical,
            "virtual": VIRTUAL if active else None,
            "rate": 48000,
            "hrtfAvailable": hrtf_available(),
            "backend": (
                "PipeWire SOFA"
                if runtime.mode == "HRTF"
                else "PipeWire + native pan DSP"
            ),
            "pan": cfg["pan"],
            "elevation": cfg["elevation"],
            "width": cfg["width"],
            "intensity": cfg["intensity"],
            "reason": reason,
        },
    )


def activate(runtime: Runtime, cfg: dict) -> bool:
    physical = physical_sink()
    if not physical:
        runtime_status(runtime, cfg, False, "No physical audio sink")
        return False

    pname = props(physical).get("node.name")
    prior = default_name()
    remembered = read_state()
    atomic(
        STATE,
        {
            "prior_default": (
                prior
                if prior and not prior.startswith(VIRTUAL)
                else remembered.get("prior_default") or pname
            ),
            "physical": pname,
        },
    )

    requested = cfg["mode"]
    if runtime.start(cfg, physical):
        runtime_status(runtime, cfg, True)
        return True

    if requested == "HRTF":
        fallback = dict(cfg)
        fallback["mode"] = "Pan"
        if runtime.start(fallback, physical):
            runtime_status(
                runtime,
                fallback,
                True,
                "HRTF activation failed; running Pan fallback",
            )
            return True

    reason = runtime.last_error or "Activation failed"
    restore_default()
    runtime_status(runtime, cfg, False, reason)
    return False



def serve() -> int:
    runtime = Runtime()
    alive = True

    def stop(*_args) -> None:
        nonlocal alive
        alive = False

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    last_cfg = None
    last_stamp = None
    next_health = 0.0

    try:
        while alive:
            try:
                stamp = CONFIG.stat().st_mtime_ns
            except OSError:
                stamp = -1

            if stamp != last_stamp or last_cfg is None:
                cfg = config()
                last_stamp = stamp

                if not cfg["enabled"]:
                    if runtime.mode is not None:
                        runtime.terminate()
                        restore_default()
                    runtime_status(runtime, cfg, False, "Disabled")
                elif runtime.mode is None:
                    activate(runtime, cfg)
                elif cfg["mode"] != runtime.mode:
                    runtime.terminate()
                    restore_default()
                    activate(runtime, cfg)
                elif runtime.mode == "HRTF":
                    runtime.set_hrtf_target(cfg)
                    runtime_status(
                        runtime, cfg, runtime.healthy(check_node=False)
                    )
                else:
                    # Pan DSP consumes the same config file directly and
                    # interpolates it per sample; do not rebuild its graph.
                    runtime_status(
                        runtime, cfg, runtime.healthy(check_node=False)
                    )
                last_cfg = cfg

            now = time.monotonic()
            if runtime.mode == "HRTF":
                runtime.tick_hrtf()

            if now >= next_health:
                next_health = now + 2.0
                cfg = last_cfg or config()
                if (
                    cfg["enabled"]
                    and (runtime.mode is None or not runtime.healthy())
                ):
                    runtime.terminate()
                    restore_default()
                    activate(runtime, cfg)
                elif runtime.mode is not None:
                    runtime_status(runtime, cfg, True)

            time.sleep(0.02)
    finally:
        runtime.terminate()
        restore_default()

    return 0


def service_active() -> bool:
    return (
        subprocess.run(
            [
                "systemctl",
                "--user",
                "is-active",
                "--quiet",
                "caelestia-spatial-audio.service",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        ).returncode
        == 0
    )


def main(argv: list[str]) -> int:
    cmd = argv[1] if len(argv) > 1 else "status"

    if cmd == "configure":
        try:
            change = json.loads(argv[2])
        except (IndexError, json.JSONDecodeError):
            return 64

        updated = config()
        updated.update({k: change[k] for k in set(DEFAULT) & change.keys()})
        atomic(CONFIG, updated)
        normalized = config()

        if normalized["enabled"]:
            if not service_active():
                subprocess.run(
                    [
                        "systemctl",
                        "--user",
                        "start",
                        "caelestia-spatial-audio.service",
                    ],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
        else:
            if service_active():
                subprocess.run(
                    [
                        "systemctl",
                        "--user",
                        "stop",
                        "caelestia-spatial-audio.service",
                    ],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            else:
                restore_default()
        return 0

    if cmd == "stop":
        if service_active():
            subprocess.run(
                [
                    "systemctl",
                    "--user",
                    "stop",
                    "caelestia-spatial-audio.service",
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        restore_default()
        return 0

    if cmd == "dry-run":
        physical = physical_sink()
        pname = props(physical).get("node.name") if physical else None
        cfg = config()
        print(
            json.dumps(
                {
                    "config": cfg,
                    "physical": pname,
                    "graph": (
                        graph(cfg, pname or "missing")
                        if pname
                        else None
                    ),
                    "hrtfAvailable": hrtf_available(),
                }
            )
        )
        return 0

    if cmd == "status":
        try:
            print(RUNTIME.read_text())
        except OSError:
            physical = physical_sink()
            print(
                json.dumps(
                    {
                        "active": False,
                        "backend": "PipeWire",
                        "hrtfAvailable": hrtf_available(),
                        "physical": (
                            props(physical).get("node.name")
                            if physical
                            else None
                        ),
                    }
                )
            )
        return 0

    if cmd == "serve":
        return serve()

    return 64


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
