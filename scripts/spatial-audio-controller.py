#!/usr/bin/env python3
"""Crash-cleaned PipeWire owner for Caelestia Spatial Audio."""
from __future__ import annotations
import json, os, signal, subprocess, sys, time
from pathlib import Path

APP = "caelestia-spatial-audio"; VIRTUAL = "caelestia_spatial_audio"
SOFA = Path("/usr/share/libmysofa/MIT_KEMAR_normal_pinna.sofa")
ROOT = Path(__file__).resolve().parents[1]
CONFIG = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / APP / "config.json"
STATE = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state")) / APP / "state.json"
RUNTIME = Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp")) / APP / "status.json"
DEFAULT = {"enabled": False, "mode": "Pan", "pan": 0.0, "elevation": 0.0, "width": 1.0, "intensity": 1.0, "movement_ms": 220}

def atomic(path, data):
    path.parent.mkdir(parents=True, exist_ok=True); tmp = path.with_suffix(path.suffix + ".new")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n"); tmp.replace(path)
def config():
    try: raw = json.loads(CONFIG.read_text())
    except (OSError, json.JSONDecodeError): raw = {}
    cfg = DEFAULT | {k: raw[k] for k in DEFAULT if k in raw}; cfg["mode"] = "HRTF" if str(cfg["mode"]).upper() == "HRTF" else "Pan"
    for k, lo, hi in (("pan",-1,1),("elevation",-45,45),("width",0,1),("intensity",0,1),("movement_ms",20,2000)): cfg[k] = max(lo,min(hi,float(cfg[k])))
    cfg["movement_ms"] = int(cfg["movement_ms"]); cfg["enabled"] = bool(cfg["enabled"]); return cfg
def dump(): return json.loads(subprocess.check_output(["pw-dump"], text=True))
def props(n): return n.get("info",{}).get("props",{})
def nodes(): return [n for n in dump() if n.get("type") == "PipeWire:Interface:Node"]
def default_name():
    r = subprocess.run(["wpctl","inspect","@DEFAULT_AUDIO_SINK@"],text=True,capture_output=True)
    for line in r.stdout.splitlines():
        if "node.name" in line and "=" in line: return line.split("=",1)[1].strip().strip('"')
    return None
def physical_sink():
    current = default_name(); candidates = [n for n in nodes() if props(n).get("media.class") == "Audio/Sink" and not props(n).get("node.name","").startswith(VIRTUAL)]
    # Once our virtual sink is default, asking WirePlumber for "the default"
    # must not make us pick an arbitrary HDMI sink on the next service tick.
    # Keep driving the exact physical endpoint captured before activation.
    if current and current.startswith(VIRTUAL):
        try: saved = json.loads(STATE.read_text()).get("physical")
        except (OSError, json.JSONDecodeError): saved = None
        if saved:
            remembered = next((n for n in candidates if props(n).get("node.name") == saved), None)
            if remembered: return remembered
    return next((n for n in candidates if props(n).get("node.name") == current), candidates[0] if candidates else None)
def node_id(name): return next((int(n["id"]) for n in nodes() if props(n).get("node.name") == name), None)
def q(s): return '"' + s.replace('"','\\"') + '"'
def graph(cfg, physical):
    if cfg["mode"] == "Pan":
        return f'''{{ node.description = "Caelestia Spatial Audio (Pan)" filter.graph = {{ nodes = [ {{ type = builtin name = copy label = copy }} ] inputs = [ "copy:In L" "copy:In R" ] outputs = [ "copy:Out L" "copy:Out R" ] }} audio.channels = 2 audio.position = [ FL FR ] capture.props = {{ node.name = {q(VIRTUAL)} media.class = Audio/Sink node.virtual = true }} playback.props = {{ node.name = {q(VIRTUAL+'_raw')} node.passive = true node.dont-reconnect = true target.object = 0 }} }}'''
    az, el = round(cfg["pan"]*90,2), round(cfg["elevation"],2)
    return f'''{{ node.description = "Caelestia Spatial Audio (HRTF)" filter.graph = {{ nodes = [ {{ type = sofa name = hrtf label = spatializer config = {{ filename = {q(str(SOFA))} }} control = {{ Azimuth = {az} Elevation = {el} }} }} ] inputs = [ "hrtf:In" ] outputs = [ "hrtf:Out L" "hrtf:Out R" ] }} audio.channels = 1 audio.position = [ MONO ] capture.props = {{ node.name = {q(VIRTUAL)} media.class = Audio/Sink node.virtual = true }} playback.props = {{ node.name = {q(VIRTUAL+'_hrtf')} node.passive = true target.object = {q(physical)} }} }}'''

class Runtime:
    def __init__(self): self.cli=self.rec=self.dsp=self.play=None
    def terminate(self):
        for p in (self.rec,self.dsp,self.play,self.cli):
            if p and p.poll() is None: p.terminate()
        for p in (self.rec,self.dsp,self.play,self.cli):
            if p:
                try: p.wait(timeout=1)
                except subprocess.TimeoutExpired: p.kill()
    def start(self,cfg,physical):
        name=props(physical).get("node.name")
        if not name or name.startswith(VIRTUAL): return False
        self.cli=subprocess.Popen(["pw-cli"],stdin=subprocess.PIPE,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,text=True); self.cli.stdin.write("load-module libpipewire-module-filter-chain "+graph(cfg,name)+"\n"); self.cli.stdin.flush()
        for _ in range(25):
            if node_id(VIRTUAL) is not None: break
            time.sleep(.04)
        vid=node_id(VIRTUAL)
        if vid is None: self.terminate(); return False
        subprocess.run(["wpctl","set-default",str(vid)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        if cfg["mode"] == "Pan":
            dspbin=ROOT/"native/spatial-dsp"
            if not dspbin.is_file(): self.terminate(); return False
            self.rec=subprocess.Popen(["pw-cat","--record","--raw","--format","f32","--rate","48000","--channels","2","--target",VIRTUAL,"-P","node.name=caelestia_spatial_audio_capture"],stdout=subprocess.PIPE,stderr=subprocess.DEVNULL)
            self.dsp=subprocess.Popen([str(dspbin),str(CONFIG),str(STATE)],stdin=self.rec.stdout,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL); self.rec.stdout.close()
            self.play=subprocess.Popen(["pw-cat","--playback","--raw","--format","f32","--rate","48000","--channels","2","--target",name,"-P","node.name=caelestia_spatial_audio_playback,node.dont-reconnect=true"],stdin=self.dsp.stdout,stderr=subprocess.DEVNULL); self.dsp.stdout.close()
        return True
def restore_default():
    try: prior=json.loads(STATE.read_text()).get("prior_default")
    except (OSError,json.JSONDecodeError): prior=None
    if prior and not prior.startswith(VIRTUAL):
        ident=node_id(prior)
        if ident is not None: subprocess.run(["wpctl","set-default",str(ident)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    RUNTIME.unlink(missing_ok=True)
def serve():
    runtime=Runtime(); alive=True
    def stop(*_):
        nonlocal alive; alive=False
    signal.signal(signal.SIGTERM,stop); signal.signal(signal.SIGINT,stop); last=None
    try:
        while alive:
            cfg=config(); physical=physical_sink()
            # Pan values are read live by the native DSP. Rebuilding its graph
            # for every slider frame would cause clicks and defeat interpolation.
            graph_cfg = {"enabled": cfg["enabled"], "mode": cfg["mode"]}
            if cfg["mode"] == "HRTF": graph_cfg.update(pan=cfg["pan"], elevation=cfg["elevation"])
            fingerprint=json.dumps(graph_cfg,sort_keys=True)+str(props(physical).get("node.name") if physical else "")
            if fingerprint != last:
                runtime.terminate(); restore_default(); ok=False
                if cfg["enabled"] and physical:
                    prior=default_name()
                    if prior and not prior.startswith(VIRTUAL): atomic(STATE,{"prior_default":prior,"physical":props(physical).get("node.name")})
                    if cfg["mode"] != "HRTF" or SOFA.is_file(): ok=runtime.start(cfg,physical)
                    if not ok and cfg["mode"] == "HRTF": cfg["mode"]="Pan"; ok=runtime.start(cfg,physical)
                atomic(RUNTIME,{"active":ok,"mode":cfg["mode"],"physical":props(physical).get("node.name") if physical else None,"virtual":VIRTUAL if ok else None,"rate":48000,"sofa":SOFA.is_file(),"backend":"PipeWire filter-chain"}); last=fingerprint
            time.sleep(.12)
    finally: runtime.terminate(); restore_default()
    return 0
def main(argv):
    cmd=argv[1] if len(argv)>1 else "status"
    if cmd == "configure":
        try: change=json.loads(argv[2])
        except (IndexError,json.JSONDecodeError): return 64
        old=config(); old.update({k:change[k] for k in set(DEFAULT)&change.keys()}); atomic(CONFIG,old); subprocess.run(["systemctl","--user","start" if old["enabled"] else "stop","caelestia-spatial-audio.service"],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL); return 0
    if cmd == "stop": restore_default(); return 0
    if cmd == "dry-run":
        p=physical_sink(); print(json.dumps({"config":config(),"physical":props(p).get("node.name") if p else None,"graph":graph(config(),props(p).get("node.name","missing")) if p else None})); return 0
    if cmd == "status":
        try: print(RUNTIME.read_text())
        except OSError: print(json.dumps({"active":False,"backend":"PipeWire filter-chain","sofa":SOFA.is_file()}))
        return 0
    if cmd == "serve": return serve()
    return 64
if __name__ == "__main__": raise SystemExit(main(sys.argv))
