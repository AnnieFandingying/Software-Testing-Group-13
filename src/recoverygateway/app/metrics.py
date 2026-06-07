from prometheus_client import Counter, Histogram

COMMANDS_TOTAL = Counter(
    "recovery_gateway_commands_total",
    "Recovery commands received by the gateway.",
    ("action", "target", "result"),
)

COMMAND_LATENCY_SECONDS = Histogram(
    "recovery_gateway_command_latency_seconds",
    "Recovery command handling latency.",
    ("action",),
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)

DEGRADE_STATE = Counter(
    "recovery_gateway_degrade_transitions_total",
    "Service degradation state transitions.",
    ("service", "mode"),
)
