#!/usr/bin/env bash
set -euo pipefail
systemctl --user disable --now caelestia-spatial-audio.service 2>/dev/null || true
systemctl --user daemon-reload
echo "Spatial Audio stopped; the prior default sink was restored. Source retained."
