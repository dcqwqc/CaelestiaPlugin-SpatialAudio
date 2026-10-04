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
TEST_VIRTUAL = "caelestia_spatial_audio_test"
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


def sink_gain(name: str) -> tuple[float, bool] | None:
    ident = node_id(name)
    if ident is None:
        return None
    result = subprocess.run(
        ["wpctl", "get-volume", str(ident)],
        text=True,
        capture_output=True,
    )
    if result.returncode != 0:
        return None
    parts = result.stdout.split()
    try:
        volume = float(parts[1])
    except (IndexError, ValueError):
        return None
    return volume, "[MUTED]" in result.stdout


def set_sink_gain(name: str, volume: float, muted: bool | None = None) -> bool:
    ident = node_id(name)
    if ident is None:
        return False
    volume_result = subprocess.run(
        ["wpctl", "set-volume", str(ident), f"{max(0.0, float(volume)):.6f}"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if volume_result.returncode != 0:
        return False
    if muted is not None:
        subprocess.run(
            ["wpctl", "set-mute", str(ident), "1" if muted else "0"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    return True


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


def pan_matrix(pan: float, width: float, intensity: float) -> tuple[float, float, float, float]:
    """Return L<-L, L<-R, R<-L, R<-R gains for the stereo stage."""
    p = max(-1.0, min(1.0, float(pan)))
    w = max(0.0, min(1.0, float(width)))
    t = max(0.0, min(1.0, float(intensity)))

    a = 0.5 * (1.0 + w)
    b = 0.5 * (1.0 - w)

    if p >= 0.0:
        pll = (1.0 - p) * a
        plr = (1.0 - p) * b
        prl = (1.0 - 0.5 * p) * b + 0.5 * p * a
        prr = (1.0 - 0.5 * p) * a + 0.5 * p * b
    else:
        qv = -p
        pll = (1.0 - 0.5 * qv) * a + 0.5 * qv * b
        plr = (1.0 - 0.5 * qv) * b + 0.5 * qv * a
        prl = (1.0 - qv) * b
        prr = (1.0 - qv) * a

    return (
        (1.0 - t) + t * pll,
        t * plr,
        t * prl,
        (1.0 - t) + t * prr,
    )


def graph(cfg: dict, physical: str, virtual: str = VIRTUAL) -> str:
    if cfg["mode"] == "Pan":
        ll, lr, rl, rr = pan_matrix(cfg["pan"], cfg["width"], cfg["intensity"])
        return f'''{{ node.description = "Caelestia Spatial Audio (Pan)"
filter.graph = {{
  nodes = [
    {{ type = builtin name = copyL label = copy }}
    {{ type = builtin name = copyR label = copy }}
    {{ type = builtin name = mixL label = mixer control = {{
       "Gain 1" = {ll:.8f} "Gain 2" = {lr:.8f}
    }} }}
    {{ type = builtin name = mixR label = mixer control = {{
       "Gain 1" = {rl:.8f} "Gain 2" = {rr:.8f}
    }} }}
  ]
  links = [
    {{ output = "copyL:Out" input = "mixL:In 1" }}
    {{ output = "copyR:Out" input = "mixL:In 2" }}
    {{ output = "copyL:Out" input = "mixR:In 1" }}
    {{ output = "copyR:Out" input = "mixR:In 2" }}
  ]
  inputs = [ "copyL:In" "copyR:In" ]
  outputs = [ "mixL:Out" "mixR:Out" ]
}}
audio.channels = 2
audio.position = [ FL FR ]
capture.props = {{
  node.name = {q(virtual)}
  media.class = Audio/Sink
  node.virtual = true
  audio.channels = 2
  audio.position = [ FL FR ]
}}
playback.props = {{
  node.name = {q(virtual + "_out")}
  node.passive = true
  node.dont-reconnect = true
  target.object = {q(physical)}
  audio.channels = 2
  audio.position = [ FL FR ]
  stream.dont-remix = true
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
  node.name = {q(virtual)}
  media.class = Audio/Sink
  node.virtual = true
}}
playback.props = {{
  node.name = {q(virtual + "_hrtf")}
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
        self.vid: int | None = None
        self.mode: str | None = None
        self.physical: str | None = None
        self.last_error: str | None = None
        self.current_hrtf = [0.0, 0.0, 1.0]
        self.start_hrtf = [0.0, 0.0, 1.0]
        self.target_hrtf = [0.0, 0.0, 1.0]
        self.move_started = 0.0
        self.move_duration = 0.22
        self.current_pan = [0.0, 1.0, 1.0]
        self.start_pan = [0.0, 1.0, 1.0]
        self.target_pan = [0.0, 1.0, 1.0]

    def terminate(self) -> None:
        for proc in (self.cli,):
            if proc and proc.poll() is None:
                proc.terminate()
        for proc in (self.cli,):
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
        self.cli = None
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
            self.current_pan = [cfg["pan"], cfg["width"], cfg["intensity"]]
            self.start_pan = self.current_pan.copy()
            self.target_pan = self.current_pan.copy()
            self.move_started = time.monotonic()
            self.move_duration = max(0.02, cfg["movement_ms"] / 1000.0)
            if not self._send_pan(*self.current_pan):
                self.last_error = "Could not set Pan controls"
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
        if check_node and node_id(VIRTUAL) != self.vid:
            return False
        return True

    def _send_pan(self, pan: float, width: float, intensity: float) -> bool:
        if self.vid is None:
            return False
        ll, lr, rl, rr = pan_matrix(pan, width, intensity)
        payload = (
            '{ params = [ '
            '"mixL:Gain 1" %.8f "mixL:Gain 2" %.8f '
            '"mixR:Gain 1" %.8f "mixR:Gain 2" %.8f ] }'
            % (ll, lr, rl, rr)
        )
        return self._command(f"set-param {self.vid} Props {payload}")

    def set_pan_target(self, cfg: dict) -> None:
        if self.mode != "Pan":
            return
        target = [cfg["pan"], cfg["width"], cfg["intensity"]]
        if all(abs(a - b) < 1e-6 for a, b in zip(target, self.target_pan)):
            return
        self.start_pan = self.current_pan.copy()
        self.target_pan = target
        self.move_started = time.monotonic()
        self.move_duration = max(0.02, cfg["movement_ms"] / 1000.0)

    def tick_pan(self) -> None:
        if self.mode != "Pan" or not self.healthy(check_node=False):
            return
        elapsed = time.monotonic() - self.move_started
        t = min(1.0, elapsed / self.move_duration)
        ease = t * t * (3.0 - 2.0 * t)
        values = [
            a + (b - a) * ease
            for a, b in zip(self.start_pan, self.target_pan)
        ]
        changed = any(
            abs(a - b) > 1e-4 for a, b in zip(values, self.current_pan)
        )
        final_not_sent = t >= 1.0 and any(
            abs(a - b) > 1e-9
            for a, b in zip(self.current_pan, self.target_pan)
        )
        if changed or final_not_sent:
            self.current_pan = values
            self._send_pan(*values)

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
        changed = any(
            abs(a - b) > 1e-4 for a, b in zip(values, self.current_hrtf)
        )
        final_not_sent = t >= 1.0 and any(
            abs(a - b) > 1e-9
            for a, b in zip(self.current_hrtf, self.target_hrtf)
        )
        if changed or final_not_sent:
            self.current_hrtf = values
            self._send_hrtf(*values)


def restore_default() -> None:
    remembered = read_state()
    physical_name = remembered.get("physical")
    for name in (remembered.get("prior_default"), physical_name):
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

    # Spatial Audio owns the user-facing virtual sink while active. Restore the
    # physical speaker's previous hardware gain/mute state when that layer is
    # removed so enabling the plugin is completely reversible.
    if isinstance(physical_name, str):
        saved_volume = remembered.get("physical_volume")
        saved_muted = remembered.get("physical_muted")
        if isinstance(saved_volume, (int, float)):
            set_sink_gain(physical_name, float(saved_volume), bool(saved_muted))

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
                else "PipeWire matrix pan"
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

    # Keep exactly one user-facing gain stage. If the physical speaker stays at
    # (for example) 50%, Caelestia's virtual 100% is silently multiplied by
    # that 0.5 hardware gain and sounds far too quiet. Preserve the old physical
    # state once, then hold the hardware sink at unity/unmuted while Spatial
    # Audio is active. AudioBoost can then make 100% mean normal gain and >100%
    # mean intentional boost.
    saved_gain = None
    if remembered.get("physical") == pname and isinstance(remembered.get("physical_volume"), (int, float)):
        saved_gain = (float(remembered["physical_volume"]), bool(remembered.get("physical_muted", False)))
    if saved_gain is None:
        saved_gain = sink_gain(pname) or (1.0, False)

    atomic(
        STATE,
        {
            "prior_default": (
                prior
                if prior and not prior.startswith(VIRTUAL)
                else remembered.get("prior_default") or pname
            ),
            "physical": pname,
            "physical_volume": saved_gain[0],
            "physical_muted": saved_gain[1],
        },
    )
    set_sink_gain(pname, 1.0, False)

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
                    runtime.set_pan_target(cfg)
                    runtime_status(
                        runtime, cfg, runtime.healthy(check_node=False)
                    )
                last_cfg = cfg

            now = time.monotonic()
            if runtime.mode == "HRTF":
                runtime.tick_hrtf()
            elif runtime.mode == "Pan":
                runtime.tick_pan()

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


def play_test_tone(target: str | None = None) -> bool:
    """Play a short desktop sound, optionally into one explicit PipeWire sink."""
    sound = Path("/usr/share/sounds/freedesktop/stereo/audio-volume-change.oga")
    if not sound.is_file():
        sound = Path("/usr/share/sounds/alsa/Front_Center.wav")
    if not sound.is_file():
        return False

    command = ["pw-play", "--volume", "0.16"]
    if target:
        command += ["--target", target]
    command.append(str(sound))

    try:
        process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        # On this PipeWire build pw-play can keep the stream alive after the
        # short clip has been consumed. Let the audible part finish, then close
        # the client explicitly so a Settings test never leaves a stray stream.
        time.sleep(0.85)
        code = process.poll()
        if code is None:
            process.terminate()
            try:
                process.wait(timeout=0.5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=0.5)
            return True
        return code == 0
    except (OSError, subprocess.SubprocessError):
        return False


def play_isolated_test(cfg: dict) -> bool:
    """Play one probe through a private filter without changing global defaults."""
    physical = physical_sink()
    if not physical:
        return False

    physical_name = props(physical).get("node.name")
    if not physical_name or physical_name.startswith(VIRTUAL):
        return False
    if cfg["mode"] == "HRTF" and not hrtf_available():
        return False

    test_name = f"{TEST_VIRTUAL}_{os.getpid()}_{time.monotonic_ns()}"
    cli = None
    try:
        cli = subprocess.Popen(
            ["pw-cli"],
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        if not cli.stdin:
            return False
        graph_args = " ".join(graph(cfg, physical_name, test_name).splitlines())
        cli.stdin.write(
            "load-module libpipewire-module-filter-chain " + graph_args + "
"
        )
        cli.stdin.flush()

        for _ in range(50):
            if node_id(test_name) is not None:
                break
            if cli.poll() is not None:
                return False
            time.sleep(0.04)
        else:
            return False

        # Explicit target is the key safety property: the probe never becomes
        # the default sink, so existing app streams and all capture devices stay put.
        return play_test_tone(test_name)
    except (OSError, subprocess.SubprocessError):
        return False
    finally:
        if cli and cli.poll() is None:
            cli.terminate()
            try:
                cli.wait(timeout=1.0)
            except subprocess.TimeoutExpired:
                cli.kill()
                try:
                    cli.wait(timeout=0.5)
                except subprocess.TimeoutExpired:
                    pass

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

    if cmd == "test-tone":
        try:
            change = json.loads(argv[2]) if len(argv) > 2 else {}
        except json.JSONDecodeError:
            return 64

        test_cfg = config()
        test_cfg.update({k: change[k] for k in set(DEFAULT) & change.keys()})
        test_cfg["enabled"] = True
        test_cfg["mode"] = (
            "HRTF" if str(test_cfg["mode"]).upper() == "HRTF" else "Pan"
        )
        return 0 if play_isolated_test(test_cfg) else 1

    if cmd == "test-sweep":
        try:
            change = json.loads(argv[2]) if len(argv) > 2 else {}
        except json.JSONDecodeError:
            return 64

        test_cfg = config()
        test_cfg.update({k: change[k] for k in set(DEFAULT) & change.keys()})
        test_cfg["enabled"] = True
        test_cfg["mode"] = "Pan"

        ok = True
        for pan in (-0.85, 0.0, 0.85):
            step = dict(test_cfg)
            step["pan"] = pan
            ok = play_isolated_test(step) and ok
        return 0 if ok else 1

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
