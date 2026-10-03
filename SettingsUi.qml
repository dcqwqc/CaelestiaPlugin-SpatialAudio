pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Quickshell.Io
import qs.components
import qs.modules.nexus.common

ColumnLayout {
    id: root
    property var settings: null
    property bool orbiting: false
    property string diagnostics: qsTr("Checking PipeWire…")
    Layout.fillWidth: true
    spacing: Tokens.spacing.extraSmall

    function clamp(v, lo, hi): real {
        return Math.max(lo, Math.min(hi, v));
    }
    function setPan(v): void {
        if (settings)
            settings.pan = clamp(v, -1, 1);
    }
    function refresh(): void {
        status.running = true;
    }
    function configure(): void {
        if (settings)
            command.running = true;
    }

    Process {
        id: status
        command: [Qt.resolvedUrl("scripts/spatial-audio-controller.py").toString().replace("file://", ""), "status"]
        running: true
        stdout: StdioCollector {
            onStreamFinished: root.diagnostics = text.length ? text.trim() : qsTr("Controller unavailable")
        }
    }
    Process {
        id: command
        command: [Qt.resolvedUrl("scripts/spatial-audio-controller.py").toString().replace("file://", ""), "configure", JSON.stringify({
                enabled: Boolean(root.settings?.enabled),
                mode: String(root.settings?.mode),
                pan: Number(root.settings?.pan),
                elevation: Number(root.settings?.elevation),
                width: Number(root.settings?.width),
                intensity: Number(root.settings?.intensity),
                movement_ms: Number(root.settings?.movementMs)
            })]
        running: false
        onExited: root.refresh()
    }
    Timer {
        id: orbit
        interval: 16
        repeat: true
        onTriggered: root.setPan(Math.sin(Date.now() / Math.max(250, Number(root.settings?.movementMs ?? 220) * 8)))
    }

    SectionHeader {
        first: true
        text: qsTr("Spatial audio")
    }
    SwitchRow {
        Layout.fillWidth: true
        first: true
        label: qsTr("Enable system routing")
        subtext: qsTr("Normal apps use a PipeWire virtual sink; the prior output is restored when disabled.")
        checked: Boolean(root.settings?.enabled)
        onToggled: checked => {
            if (root.settings) {
                root.settings.enabled = checked;
                root.configure();
            }
        }
    }
    RowLayout {
        Layout.fillWidth: true
        StyledText {
            text: qsTr("Mode")
            Layout.fillWidth: true
        }
        ComboBox {
            model: [qsTr("Pan"), qsTr("HRTF")]
            currentIndex: String(root.settings?.mode) === "HRTF" ? 1 : 0
            onActivated: i => {
                if (root.settings) {
                    root.settings.mode = i === 1 ? "HRTF" : "Pan";
                    root.configure();
                }
            }
        }
    }
    SliderRow {
        Layout.fillWidth: true
        label: String(root.settings?.mode) === "HRTF" ? qsTr("Azimuth") : qsTr("Pan")
        from: -1
        to: 1
        value: Number(root.settings?.pan ?? 0)
        valueLabel: Number(value).toFixed(2)
        onMoved: v => {
            root.setPan(v);
            root.configure();
        }
    }
    SliderRow {
        Layout.fillWidth: true
        visible: String(root.settings?.mode) === "HRTF"
        label: qsTr("Elevation")
        from: -45
        to: 45
        value: Number(root.settings?.elevation ?? 0)
        valueLabel: Number(value).toFixed(0) + "°"
        onMoved: v => {
            if (root.settings)
                root.settings.elevation = v;
            root.configure();
        }
    }
    SliderRow {
        Layout.fillWidth: true
        visible: String(root.settings?.mode) !== "HRTF"
        label: qsTr("Stereo width")
        from: 0
        to: 1
        value: Number(root.settings?.width ?? 1)
        valueLabel: Number(value).toFixed(2)
        onMoved: v => {
            if (root.settings)
                root.settings.width = v;
            root.configure();
        }
    }
    SliderRow {
        Layout.fillWidth: true
        label: qsTr("Intensity")
        from: 0
        to: 1
        value: Number(root.settings?.intensity ?? 1)
        valueLabel: Number(value).toFixed(2)
        onMoved: v => {
            if (root.settings)
                root.settings.intensity = v;
            root.configure();
        }
    }
    StepperRow {
        Layout.fillWidth: true
        label: qsTr("Movement smoothing")
        value: Number(root.settings?.movementMs ?? 220)
        from: 20
        to: 2000
        stepSize: 10
        onMoved: v => {
            if (root.settings) {
                root.settings.movementMs = Math.round(v);
                root.configure();
            }
        }
    }
    SectionHeader {
        text: qsTr("Position")
    }
    RowLayout {
        Layout.fillWidth: true
        Button {
            text: qsTr("Center")
            onClicked: {
                root.setPan(0);
                root.configure();
            }
        }
        Button {
            text: qsTr("Left")
            onClicked: {
                root.setPan(-1);
                root.configure();
            }
        }
        Button {
            text: qsTr("Right")
            onClicked: {
                root.setPan(1);
                root.configure();
            }
        }
        Button {
            text: qsTr("Wide")
            onClicked: {
                if (root.settings) {
                    root.settings.width = 1;
                    root.setPan(0);
                    root.configure();
                }
            }
        }
    }
    RowLayout {
        Layout.fillWidth: true
        Button {
            text: root.orbiting ? qsTr("Stop demo") : qsTr("Orbit demo")
            onClicked: {
                root.orbiting = !root.orbiting;
                orbit.running = root.orbiting;
                if (!root.orbiting)
                    root.configure();
            }
        }
        Button {
            text: qsTr("Left → Right")
            onClicked: {
                root.setPan(-1);
                sweep.start();
            }
        }
        NumberAnimation {
            id: sweep
            target: root.settings
            property: "pan"
            from: -1
            to: 1
            duration: Math.max(500, Number(root.settings?.movementMs ?? 220) * 8)
            onFinished: root.configure()
        }
    }
    SectionHeader {
        text: qsTr("Diagnostics")
    }
    StyledText {
        Layout.fillWidth: true
        text: root.diagnostics
        wrapMode: Text.Wrap
        color: Colours.palette.m3outline
        font: Tokens.font.body.small
    }
    Button {
        text: qsTr("Refresh diagnostics")
        onClicked: root.refresh()
    }
}
