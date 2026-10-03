#!/usr/bin/env python3
import json
from pathlib import Path
p=Path.home()/".config/caelestia/plugins.json"; d=json.loads(p.read_text())
d.setdefault("enabled",[])
if "dcqwqc/spatialaudio" not in d["enabled"]: d["enabled"].append("dcqwqc/spatialaudio")
s=d.setdefault("settings",{}).setdefault("dcqwqc/spatialaudio",{})
for k,v in {"enabled":True,"mode":"Pan","pan":0,"elevation":0,"width":1,"intensity":1,"movementMs":220}.items(): s.setdefault(k,v)
p.write_text(json.dumps(d,indent=4)+"\n")
