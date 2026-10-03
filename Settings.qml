import Caelestia.Plugins

SettingsObject {
    property bool enabled: false
    property string mode: "Pan"
    property real pan: 0
    property real elevation: 0
    property real width: 1
    property real intensity: 1
    property int movementMs: 220

    SettingMeta on enabled {
        label: "Enable spatial audio"
        icon: "surround_sound"
        inputType: SettingMeta.Switch
    }
    SettingMeta on mode {
        label: "Mode"
        description: "Pan works on stereo speakers. HRTF uses the installed SOFA profile."
        inputType: SettingMeta.SplitButton
        options: ["Pan", "HRTF"]
    }
    SettingMeta on pan {
        label: "Pan / azimuth"
        inputType: SettingMeta.Slider
        min: -1
        max: 1
        step: 0.01
    }
    SettingMeta on elevation {
        label: "Elevation"
        inputType: SettingMeta.Slider
        min: -45
        max: 45
        step: 1
    }
    SettingMeta on width {
        label: "Stereo width"
        inputType: SettingMeta.Slider
        min: 0
        max: 1
        step: 0.01
    }
    SettingMeta on intensity {
        label: "Intensity"
        inputType: SettingMeta.Slider
        min: 0
        max: 1
        step: 0.01
    }
    SettingMeta on movementMs {
        label: "Movement smoothing"
        inputType: SettingMeta.SpinBox
        min: 20
        max: 2000
        step: 10
    }
}
