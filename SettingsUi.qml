pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Layouts
import Quickshell.Io
import qs.components
import qs.components.controls
import qs.modules.nexus.common
import dcqwqc.spatialaudio

ColumnLayout {
    id: root

    property var settings: null
    property bool orbiting: false
    property string diagnostics: qsTr("Checking PipeWire…")
    property string testState: qsTr("Ready")
    property real demoPan: Number(settings?.pan ?? 0)
    readonly property string helper: Qt.resolvedUrl("scripts/spatial-audio-controller.py").toString().replace("file://", "")
    readonly property var modeChoices: [
        {
            value: "Pan",
            label: qsTr("Pan"),
            icon: "swap_horiz"
        },
        {
            value: "HRTF",
            label: qsTr("HRTF"),
            icon: "spatial_audio"
        }
    ]

    Layout.fillWidth: true
    spacing: Tokens.spacing.extraSmall

    function clamp(v, lo, hi): real {
        return Math.max(lo, Math.min(hi, v));
    }

    function setPan(v): void {
        if (settings)
            settings.pan = clamp(v, -1, 1);
        demoPan = clamp(v, -1, 1);
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

    function testPayload(mode, panValue): string {
        return JSON.stringify({
            enabled: true,
            mode: mode,
            pan: Number(panValue),
            elevation: Number(settings?.elevation ?? 0),
            width: Number(settings?.width ?? 1),
            intensity: Number(settings?.intensity ?? 1),
            movement_ms: Number(settings?.movementMs ?? 220)
        });
    }

    function playTest(panValue, forceHrtf): void {
        if (!settings || audibleTest.running)
            return;

        const nextMode = forceHrtf ? "HRTF" : String(settings.mode ?? "Pan");
        settings.enabled = true;
        settings.mode = nextMode;
        settings.pan = clamp(panValue, -1, 1);
        demoPan = settings.pan;
        testState = forceHrtf ? qsTr("Playing HRTF test at %1").arg(positionName(demoPan)) : qsTr("Playing at %1").arg(positionName(demoPan));
        audibleTest.command = [helper, "test-tone", testPayload(nextMode, demoPan)];
        audibleTest.running = true;
    }

    function playSweep(): void {
        if (!settings || audibleTest.running)
            return;

        settings.enabled = true;
        settings.mode = "Pan";
        demoPan = -0.85;
        testState = qsTr("Sweeping left → center → right…");
        sweepVisual.restart();
        audibleTest.command = [helper, "test-sweep", JSON.stringify({
                enabled: true,
                width: Number(settings.width ?? 1),
                intensity: Number(settings.intensity ?? 1),
                movement_ms: Number(settings.movementMs ?? 220),
                restorePan: Number(settings.pan ?? 0)
            })];
        audibleTest.running = true;
    }

    function positionName(panValue): string {
        if (panValue < -0.35)
            return qsTr("left");
        if (panValue > 0.35)
            return qsTr("right");
        return qsTr("center");
    }

    Process {
        id: status
        command: [root.helper, "status"]
        running: true
        stdout: StdioCollector {
            onStreamFinished: root.showStatus(text)
        }
    }

    Process {
        id: audibleTest
        onExited: {
            if (!sweepVisual.running)
                root.demoPan = Number(root.settings?.pan ?? 0);
            root.testState = qsTr("Ready · last test completed");
            root.refresh();
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

    NumberAnimation {
        id: sweepVisual
        target: root
        property: "demoPan"
        from: -0.85
        to: 0.85
        duration: 3000
        easing.type: Easing.InOutSine
        onFinished: root.demoPan = Number(root.settings?.pan ?? 0)
    }

    Component {
        id: modeMenuItem
        MenuItem {
            required property string storedValue
        }
    }

    SectionHeader {
        first: true
        text: qsTr("Spatial audio")
    }

    ToggleRow {
        Layout.fillWidth: true
        first: true
        text: qsTr("Enable system routing")
        subtext: qsTr("Routes normal apps through a reversible virtual sink. Disabling restores the previous output.")
        checked: Boolean(root.settings?.enabled)
        onToggled: checked => {
            if (root.settings)
                root.settings.enabled = checked;
        }
    }

    Item {
        id: modePicker
        Layout.fillWidth: true
        implicitHeight: modeRow.implicitHeight

        readonly property var entries: root.modeChoices.map(choice => modeMenuItem.createObject(modePicker, {
                text: choice.label,
                icon: choice.icon,
                storedValue: choice.value
            }))

        SelectRow {
            id: modeRow
            anchors.fill: parent
            label: qsTr("Mode")
            subtext: String(root.settings?.mode) === "HRTF" ? qsTr("SOFA HRTF positional rendering; strongest on headphones.") : qsTr("Speaker-safe stereo panning for the built-in speakers.")
            menuItems: modePicker.entries
            active: {
                const value = String(root.settings?.mode ?? "Pan");
                const index = root.modeChoices.findIndex(choice => choice.value === value);
                return modePicker.entries[Math.max(0, index)] ?? null;
            }
            onSelected: item => {
                if (root.settings)
                    root.settings.mode = item.storedValue;
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
        text: qsTr("Sound stage playground")
    }

    StyledRect {
        Layout.fillWidth: true
        implicitHeight: playgroundLayout.implicitHeight + Tokens.padding.large * 2
        radius: Tokens.rounding.extraLarge
        color: Colours.tPalette.m3surfaceContainer

        ColumnLayout {
            id: playgroundLayout

            anchors.fill: parent
            anchors.margins: Tokens.padding.large
            spacing: Tokens.spacing.medium

            RowLayout {
                Layout.fillWidth: true
                spacing: Tokens.spacing.medium

                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 0

                    StyledText {
                        text: qsTr("Where is the virtual source?")
                        font: Tokens.font.title.small
                        color: Colours.palette.m3onSurface
                    }

                    StyledText {
                        Layout.fillWidth: true
                        text: root.testState
                        color: Colours.palette.m3outline
                        font: Tokens.font.label.small
                        elide: Text.ElideRight
                    }
                }

                StyledRect {
                    implicitWidth: 34
                    implicitHeight: 34
                    radius: Tokens.rounding.full
                    color: audibleTest.running ? Colours.palette.m3primaryContainer : Colours.tPalette.m3surfaceContainerHighest

                    MaterialIcon {
                        anchors.centerIn: parent
                        text: audibleTest.running ? "graphic_eq" : "spatial_audio"
                        color: audibleTest.running ? Colours.palette.m3primary : Colours.palette.m3onSurfaceVariant
                        fill: audibleTest.running ? 1 : 0
                        fontStyle: Tokens.font.icon.medium
                    }
                }
            }

            Item {
                Layout.fillWidth: true
                implicitHeight: 58

                StyledRect {
                    id: stageTrack
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.verticalCenter: parent.verticalCenter
                    anchors.leftMargin: 18
                    anchors.rightMargin: 18
                    height: 5
                    radius: Tokens.rounding.full
                    color: Colours.palette.m3outlineVariant
                }

                StyledRect {
                    width: 24
                    height: 24
                    radius: Tokens.rounding.full
                    color: Colours.palette.m3primary
                    x: stageTrack.x + ((root.demoPan + 1) / 2) * Math.max(0, stageTrack.width - width)
                    y: stageTrack.y + stageTrack.height / 2 - height / 2

                    Behavior on x {
                        Anim {
                            type: Anim.FastSpatial
                        }
                    }

                    MaterialIcon {
                        anchors.centerIn: parent
                        text: "music_note"
                        color: Colours.palette.m3onPrimary
                        fontStyle: Tokens.font.icon.small
                    }
                }

                StyledText {
                    anchors.left: parent.left
                    anchors.bottom: parent.bottom
                    text: qsTr("L")
                    color: Colours.palette.m3outline
                    font: Tokens.font.label.small
                }

                StyledText {
                    anchors.horizontalCenter: parent.horizontalCenter
                    anchors.bottom: parent.bottom
                    text: qsTr("Center")
                    color: Colours.palette.m3outline
                    font: Tokens.font.label.small
                }

                StyledText {
                    anchors.right: parent.right
                    anchors.bottom: parent.bottom
                    text: qsTr("R")
                    color: Colours.palette.m3outline
                    font: Tokens.font.label.small
                }
            }

            GridLayout {
                Layout.fillWidth: true
                columns: 2
                columnSpacing: Tokens.spacing.small
                rowSpacing: Tokens.spacing.small

                IconTextButton {
                    Layout.fillWidth: true
                    Layout.preferredWidth: 1
                    icon: "arrow_back"
                    text: qsTr("Test left")
                    type: IconTextButton.Tonal
                    disabled: audibleTest.running
                    onClicked: root.playTest(-0.85, false)
                }

                IconTextButton {
                    Layout.fillWidth: true
                    Layout.preferredWidth: 1
                    icon: "radio_button_checked"
                    text: qsTr("Test center")
                    type: IconTextButton.Tonal
                    disabled: audibleTest.running
                    onClicked: root.playTest(0, false)
                }

                IconTextButton {
                    Layout.fillWidth: true
                    Layout.preferredWidth: 1
                    icon: "arrow_forward"
                    text: qsTr("Test right")
                    type: IconTextButton.Tonal
                    disabled: audibleTest.running
                    onClicked: root.playTest(0.85, false)
                }

                IconTextButton {
                    Layout.fillWidth: true
                    Layout.preferredWidth: 1
                    icon: "spatial_audio"
                    text: qsTr("Test HRTF")
                    type: IconTextButton.Tonal
                    disabled: audibleTest.running
                    onClicked: root.playTest(0.7, true)
                }
            }

            IconTextButton {
                Layout.fillWidth: true
                icon: "trending_flat"
                text: qsTr("Play left → center → right sweep")
                type: IconTextButton.Filled
                disabled: audibleTest.running
                shapeMorph: true
                verticalPadding: Tokens.padding.medium
                onClicked: root.playSweep()
            }
        }
    }

    SectionHeader {
        text: qsTr("Position")
    }

    GridLayout {
        Layout.fillWidth: true
        columns: 4
        columnSpacing: Tokens.spacing.small

        IconTextButton {
            Layout.fillWidth: true
            icon: "arrow_back"
            text: qsTr("Left")
            type: IconTextButton.Tonal
            onClicked: root.setPan(-1)
        }

        IconTextButton {
            Layout.fillWidth: true
            icon: "filter_center_focus"
            text: qsTr("Center")
            type: IconTextButton.Tonal
            onClicked: root.setPan(0)
        }

        IconTextButton {
            Layout.fillWidth: true
            icon: "arrow_forward"
            text: qsTr("Right")
            type: IconTextButton.Tonal
            onClicked: root.setPan(1)
        }

        IconTextButton {
            Layout.fillWidth: true
            icon: "open_in_full"
            text: qsTr("Wide")
            type: IconTextButton.Tonal
            disabled: String(root.settings?.mode) === "HRTF"
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
        spacing: Tokens.spacing.small

        IconTextButton {
            Layout.fillWidth: true
            icon: root.orbiting ? "stop" : "360"
            text: root.orbiting ? qsTr("Stop current-audio orbit") : qsTr("Orbit current audio")
            type: root.orbiting ? IconTextButton.Filled : IconTextButton.Tonal
            onClicked: {
                root.orbiting = !root.orbiting;
                orbit.running = root.orbiting;
            }
        }

        IconTextButton {
            Layout.fillWidth: true
            icon: "restart_alt"
            text: qsTr("Reset position")
            type: IconTextButton.Text
            onClicked: {
                root.orbiting = false;
                orbit.running = false;
                root.setPan(0);
            }
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

    IconTextButton {
        Layout.alignment: Qt.AlignRight
        icon: "refresh"
        text: qsTr("Refresh diagnostics")
        type: IconTextButton.Text
        onClicked: root.refresh()
    }
}
