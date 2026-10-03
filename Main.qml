pragma ComponentBehavior: Bound

import QtQuick
import Quickshell.Io

Item {
    id: root
    property var settings: null
    readonly property string helper: Qt.resolvedUrl("scripts/spatial-audio-controller.py").toString().replace("file://", "")
    visible: false

    function sync(): void {
        if (!settings)
            return;
        syncProcess.command = [helper, "configure", JSON.stringify({
                enabled: Boolean(settings.enabled),
                mode: String(settings.mode),
                pan: Number(settings.pan),
                elevation: Number(settings.elevation),
                width: Number(settings.width),
                intensity: Number(settings.intensity),
                movement_ms: Number(settings.movementMs)
            })];
        syncProcess.running = true;
    }

    Process {
        id: syncProcess
        running: false
    }
    Component.onCompleted: sync()
    Connections {
        target: root.settings
        function onEnabledChanged(): void {
            root.sync();
        }
        function onModeChanged(): void {
            root.sync();
        }
        function onPanChanged(): void {
            root.sync();
        }
        function onElevationChanged(): void {
            root.sync();
        }
        function onWidthChanged(): void {
            root.sync();
        }
        function onIntensityChanged(): void {
            root.sync();
        }
        function onMovementMsChanged(): void {
            root.sync();
        }
    }
}
