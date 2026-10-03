pragma ComponentBehavior: Bound

import QtQuick
import Quickshell.Io
import dcqwqc.spatialaudio

Item {
    id: root

    property var settings: null
    property bool syncQueued: false
    readonly property string helper: Qt.resolvedUrl("scripts/spatial-audio-controller.py").toString().replace("file://", "")
    visible: false

    function queueSync(): void {
        syncQueued = true;
        syncTimer.restart();
    }

    function flushSync(): void {
        if (!settings)
            return;
        if (syncProcess.running) {
            syncQueued = true;
            syncTimer.restart();
            return;
        }

        syncQueued = false;
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

    Timer {
        id: syncTimer
        interval: 35
        repeat: false
        onTriggered: root.flushSync()
    }

    Process {
        id: syncProcess
        running: false
        onExited: {
            if (root.syncQueued)
                syncTimer.restart();
        }
    }

    Component.onCompleted: queueSync()

    Connections {
        target: root.settings
        function onEnabledChanged(): void {
            root.queueSync();
        }
        function onModeChanged(): void {
            root.queueSync();
        }
        function onPanChanged(): void {
            root.queueSync();
        }
        function onElevationChanged(): void {
            root.queueSync();
        }
        function onWidthChanged(): void {
            root.queueSync();
        }
        function onIntensityChanged(): void {
            root.queueSync();
        }
        function onMovementMsChanged(): void {
            root.queueSync();
        }
    }
}
