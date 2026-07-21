DEFAULT_COLUMNS = [
    "TS",
    "Bus",
    "ID",
    "LEN",
    "DATA",
]

REAL_TIME_ANALYSIS_COLUMNS = [
    "TS",
    "Delta T",
    "Bus",
    "ID",
    "LEN",
    "DATA",
    "_ChangedBytes",
]

# Categorical palette used to auto-assign a visually-distinct color to a new
# plot series (raw/derived signal, analyze-data byte, HMI ROI variable) --
# a design token, not a Dark/Light theme color (config/theme.py's Theme is
# for UI chrome; these are picked to stay legible on either plot background).
# Shared by viewmodels/plot_viewmodel.py, services/analyze_data.py, and
# services/hmi_video_processor.py so there's one palette, not three.
SIGNAL_COLOR_PALETTE = [
    "#00ffff", "#ff6b6b", "#ffd93d", "#6bcb77", "#4d96ff",
    "#ff922b", "#cc5de8", "#f06595", "#74c0fc", "#a9e34b",
]

DEFAULT_OPTIONS = {
    "theme": "Dark",
    "dbc_modes": ["exact", "j1939"],
    "signal_match_modes": ["exact", "j1939", "bam"],
    "decode_value_modes": ["Scaled", "Raw"],
    "decode_value_scaled": "Scaled",
    "decode_value_raw": "Raw",
    "filter_types": [
        "None",
        "Moving Average",
        "Exponential Moving Average",
        "Median",
        "Gaussian",
        "Savitzky-Golay",
        "Truncate Decimals",
        "Round Decimals",
    ],
    "filter_none_type": "None",
    "filter_window_types": ["Moving Average", "Median", "Savitzky-Golay"],
    "filter_alpha_type": "Exponential Moving Average",
    "filter_sigma_type": "Gaussian",
    "filter_polyorder_type": "Savitzky-Golay",
    "filter_truncate_type": "Truncate Decimals",
    "filter_round_type": "Round Decimals",
    "line_styles": ["Solid", "Dashed", "Dotted"],
    "marker_shapes": ["Circle", "Square", "Triangle", "Diamond", "Cross", "Plus"],
    "data_types": ["uint", "int", "float32"],
    "default_data_type": "uint",
    "float_data_type": "float32",
    "connection_types": ["SSH", "Kvaser", "Replay"],
    "ssh_interfaces": ["can0", "can1"],
    "kvaser_interfaces": ["kvaser", "j2534"],
    "kvaser_default_interface": "kvaser",
    "kvaser_ports_j2534": ["J2534 for Kvaser Hardware"],
    "kvaser_ports_kvaser": ["0", "1"],
    "kvaser_default_channel": "0",
    "kvaser_bitrates": ["10000", "20000", "50000", "83333", "100000", "125000", "250000", "500000", "1000000"],
    "kvaser_default_bitrate": 250000,
    "kvaser_extra_default_kvaser": "",
    "kvaser_extra_default_j2534": "",
    "replay_speeds": ["0.25", "0.5", "1.0", "2.0", "5.0", "10.0"],
    "replay_default_speed": "1.0",
    "hmi_min_confidence": 0.5,
}
