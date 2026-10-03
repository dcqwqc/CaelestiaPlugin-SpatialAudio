#!/usr/bin/env bash
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cc -O2 -Wall -Wextra -Werror -std=c11 "$root/native/spatial-dsp.c" -lm -o "$root/native/spatial-dsp"
chmod 0755 "$root/scripts/spatial-audio-controller.py" "$root/native/spatial-dsp"
mkdir -p "$HOME/.local/share/caelestia/plugins" "$HOME/.config/systemd/user"
ln -sfn "$root" "$HOME/.local/share/caelestia/plugins/spatialaudio"
install -m 0644 "$root/systemd/caelestia-spatial-audio.service" "$HOME/.config/systemd/user/caelestia-spatial-audio.service"
systemctl --user daemon-reload
python3 "$root/scripts/plugin-enable.py"
systemctl --user enable caelestia-spatial-audio.service
echo "Installed dcqwqc/spatialaudio. Enable it in Caelestia settings; no shell restart is needed."
