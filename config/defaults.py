from __future__ import annotations

STATE_DIRECTORY_NAME = ".canlytics_state"
MAX_TP_PAYLOAD_BYTES = 1785
MAX_TP_SESSIONS = 128
DEFAULT_TP_TIMEOUT_SECONDS = 5.0
MUX_MIN_VALUES = 2
MUX_MAX_VALUES = 128
MUX_MIN_SUPPORT = 5
MUX_MIN_SUPPORT_RATIO = 0.001
MUX_MIN_COVERAGE = 0.97
MUX_MIN_CHANGE_RATE = 0.05
MUX_MIN_GAIN = 0.25
MUX_EXTENSION_TOLERANCE = 0.89
MUX_EXTENSION_MIN_DETERMINISM = 0.87
MUX_CONFIDENCE_HIGH_COVERAGE = 0.995
MUX_CONFIDENCE_HIGH_MARGIN = 0.15
MUX_CONFIDENCE_MEDIUM_MARGIN = 0.05
MUX_CONFIDENCE_STABLE_CV = 0.5
MUX_CONFIDENCE_MEDIUM_EXTENSION_AGREEMENT = 0.85
MUX_CONFIDENCE_HIGH_STABILITY = 0.8
MUX_CONFIDENCE_MEDIUM_STABILITY = 0.6
MUX_CONFIDENCE_HIGH_EXTENSION_AGREEMENT = 0.95
MUX_SENSITIVITY_MIN_GAIN_LOW = 0.40
MUX_SENSITIVITY_MIN_GAIN_HIGH = 0.10
MUX_SENSITIVITY_MAX_VALUES_LOW = 64
MUX_SENSITIVITY_MAX_VALUES_HIGH = 192
DEFAULT_TP_BAM_INTER_PACKET_SECONDS = 0.05
DEFAULT_TP_T1_SECONDS = 0.75
DEFAULT_TP_T2_SECONDS = 1.25
DEFAULT_TP_T3_SECONDS = 1.25
DEFAULT_TP_T4_SECONDS = 1.05
DEFAULT_TP_CTS_WINDOW_SIZE = 16
DEFAULT_TP_CONTROL_FRAME_TOLERANCE_SECONDS = 0.01
DEFAULT_COLUMNS = [
    "TS",
    "Bus",
    "ID",
    "Name",
    "PGN",
    "SA",
    "DA",
    "Priority",
    "PGN Name",
    "LEN",
    "Delta T",
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
    "candidate_correlation_threshold": 0.95,
    "candidate_correlation_min_samples": 12,
    "candidate_correlation_max_candidates": 500,
    "candidate_correlation_max_points": 500,
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
    "continuous_recording_directory": "~/Canlytics/Recordings",
    "memory_warning_absolute_bytes": 2 * 1024**3,
    "memory_warning_system_fraction": 0.60,
    "measurement_status_refresh_ms": 1000,
    "bus_stats_missing_after_seconds": 2.0,
    "bit_activity_min_counter_samples": 9,
    "bit_activity_min_crc_samples": 16,
    "bit_activity_ui_refresh_ms": 400,
    "reference_correlation_method": "spearman",
    "reference_correlation_window_seconds": 5.0,
    "reference_correlation_max_lag_seconds": 2.0,
    "reference_correlation_lag_step_seconds": 0.05,
    "reference_correlation_min_samples_per_window": 5,
    "mcp_session_frame_buffer": 5000,
    "mcp_session_max_frames_per_query": 500,
    "hmi_min_confidence": 0.5,
}
