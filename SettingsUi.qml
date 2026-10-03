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
    readonly property string helper: Qt.resolvedUrl("scripts/spatial-audio-controller.py").toString().replace("file://", "")
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
        if (!status.running)
            status.running = true;
    }

    function showStatus(raw): void {
        try {
            const d = JSON.parse(raw);
            const active = d.active ? qsTr("Active") : qsTr("Inactive");
            const mode = d.mode ?? String(settings?.mode ?? "Pan");
            const backend = d.backend ?? "PipeWire";
            const physical = d.physical ?? qsTr("not resolved");
            const virtualSink = d.virtual ?? qsTr("not routed");
            const hrtf = d.hrtfAvailable ? qsTr("available") : qsTr("unavailable");
            const reason = d.reason ? "\n" + qsTr("State: ") + d.reason : "";
            diagnostics = active + " · " + mode + " · " + backend + "\n" + qsTr("Physical: ") + physical + "\n" + qsTr("Virtual: ") + virtualSink + "\n" + qsTr("HRTF: ") + hrtf + reason;
        } catch (e) {
            diagnostics = raw.length ? raw.trim() : qsTr("Controller unavailable");
        }
    }

    Process {
        id: status
        command: [root.helper, "status"]
        running: true
        stdout: StdioCollector {
            onStreamFinished: root.showStatus(text)
        }
    }

    Timer {
        interval: 1500
        repeat: true
        running: root.visible
        onTriggered: root.refresh()
    }

    Timer {
        id: orbit
        interval: 33
        repeat: true
        onTriggered: {
            const period = Math.max(1200, Number(root.settings?.movementMs ?? 220) * 10);
            root.setPan(Math.sin(Date.now() * Math.PI * 2 / period));
        }
    }

    SectionHeader {
        first: true
        text: qsTr("Spatial audio")
    }

    SwitchRow {
        Layout.fillWidth: true
        first: true
        label: qsTr("Enable system routing")
        subtext: qsTr("Routes normal apps through a reversible virtual sink. Disabling restores the previous output.")
        checked: Boolean(root.settings?.enabled)
        onToggled: checked => {
            if (root.settings)
                root.settings.enabled = checked;
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
                if (root.settings)
                    root.settings.mode = i === 1 ? "HRTF" : "Pan";
            }
        }
    }

    StyledText {
        Layout.fillWidth: true
        text: String(root.settings?.mode) === "HRTF" ? qsTr("SOFA HRTF renders one positional source into stereo. It is strongest on headphones.") : qsTr("Speaker-safe stereo stage movement. Center is transparent; hard left/right keeps both source channels.")
        wrapMode: Text.Wrap
        color: Colours.palette.m3outline
        font: Tokens.font.body.small
    }

    SliderRow {
        Layout.fillWidth: true
        label: String(root.settings?.mode) === "HRTF" ? qsTr("Azimuth") : qsTr("Pan")
        from: -1
        to: 1
        value: Number(root.settings?.pan ?? 0)
        valueLabel: Number(value).toFixed(2)
        onMoved: v => root.setPan(v)
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
            if (root.settings)
                root.settings.movementMs = Math.round(v);
        }
    }

    SectionHeader {
        text: qsTr("Position")
    }

    RowLayout {
        Layout.fillWidth: true

        Button {
            text: qsTr("Center")
            onClicked: root.setPan(0)
        }
        Button {
            text: qsTr("Left")
            onClicked: root.setPan(-1)
        }
        Button {
            text: qsTr("Right")
            onClicked: root.setPan(1)
        }
        Button {
            text: qsTr("Wide")
            enabled: String(root.settings?.mode) !== "HRTF"
            onClicked: {
                if (root.settings) {
                    root.settings.width = 1;
                    root.setPan(0);
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
            }
        }

        Button {
            text: qsTr("Left → Right")
            onClicked: {
                root.orbiting = false;
                orbit.running = false;
                root.setPan(-1);
                sweep.restart();
            }
        }

        NumberAnimation {
            id: sweep
            target: root.settings
            property: "pan"
            from: -1
            to: 1
            duration: Math.max(800, Number(root.settings?.movementMs ?? 220) * 8)
            easing.type: Easing.InOutSine
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
