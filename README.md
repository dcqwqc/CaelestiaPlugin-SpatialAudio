# Caelestia Spatial Audio

`dcqwqc/spatialaudio` adds a real PipeWire virtual sink for normal desktop
applications. Pan mode is now a single PipeWire filter-chain: the virtual
sink feeds a four-gain stereo matrix directly into the selected physical sink.
There is no microphone capture client and no second/raw speaker path. The
controller interpolates matrix gains live, so UI drags and demos move smoothly.
Width and intensity are bounded to unity.

HRTF mode is genuine: the filter-chain owns SPA's `sofa` spatializer using
`/usr/share/libmysofa/MIT_KEMAR_normal_pinna.sofa`. Stereo desktop streams are
downmixed into the SOFA's mono positional input, then rendered to the physical
stereo sink. Azimuth/elevation are updated through the filter graph's live
control parameters. If SOFA cannot load, activation falls back to Pan and
diagnostics report it; it never pretends HRTF is active.

## Install / removal

Run `./install.sh`. It builds the native DSP reference/test binary, symlinks
this repository using the established Caelestia plugin convention, enables the
user controller service, and registers `dcqwqc/spatialaudio`. It does **not**
restart Quickshell. The plugin setting is enabled by the installer and its
controller comes up on the next shell setting sync (or user-service start).

`./uninstall.sh` stops the controller first, restoring the saved default
physical sink. Runtime status/config/state follow XDG directories.

## Architecture and limits

The service discovers sinks from `pw-dump`; it never stores PipeWire IDs and
refuses to target its own virtual node. Its PipeWire client owns the module,
so a crash removes the generated nodes instead of leaving orphan modules.
The preceding default sink is saved and restored on every disable/stop.

Built-in stereo speakers can only create a left-to-right image; they cannot
produce physical behind/above cues. HRTF gives binaural coloration/cues but is
most convincing on headphones. Per-app routing is intentionally not forced:
system-default routing is robust, while the controller remains structured for
future stream rules.

AudioBoost is untouched and continues to apply stream gain upstream. Keep its
ceiling sensible: Pan avoids adding gain, but AudioBoost can intentionally
amplify and clip its own streams.

If no audio returns, disable Spatial Audio; the service restores the prior
sink. Inspect `systemctl --user status caelestia-spatial-audio` and run
`scripts/spatial-audio-controller.py status`. The test suite is silent and
uses only zero PCM / disconnected filter graphs. `tests/smoke.py --real`
performs the silent create/change/teardown/default-restore lifecycle check.

### Sound stage playground

The native settings page uses Caelestia-themed controls throughout and includes audible left/center/right/HRTF probes plus a left → center → right sweep. Tests are temporary and restore the user's real mode/pan afterward. A live position indicator mirrors the test target, while normal position/orbit controls remain available for real application audio.
