"""NetFn Sensor/Event (0x04).

This board's sensor and SDR tables are genuinely empty by design (peer-
confirmed, 2026-08-24 -- see config.py's module docstring), not just
"configured but returning nothing" -- so nothing here should be read as
this board having broken sensors; there are no sensors on this EVK at
all yet.
"""

from ipmi_helpers import assert_completion_code, not_implemented, send_ipmb_command
from config import (
    CC_SUCCESS,
    CC_UNSPECIFIED_ERROR,
    CMD_GET_SENSOR_EVENT_ENABLE,
    CMD_GET_SENSOR_EVENT_STATUS,
    CMD_GET_SENSOR_READING,
    CMD_GET_SENSOR_THRESHOLD,
    CMD_GET_SENSOR_TYPE,
    NETFN_SENSOR_EVENT,
    SENSOR_NUMBER,
)


def test_get_sensor_reading_unspecified_error(bridge):
    """Get Sensor Reading (cmd 0x2D) against SENSOR_NUMBER (arbitrary --
    see that constant's comment in config.py: the value doesn't matter,
    every sensor number hits the same NULL guard).

    This board has no sensor table populated, so this deliberately does
    NOT expect the "normal" not-configured response (0xCB, "requested
    sensor/record not present"). Confirmed against source with the peer
    session: sensor_init() bails out before allocating sensor_config at
    all, leaving get_sensor_reading() to hit a null-config guard and
    return CC_UNSPECIFIED_ERROR (0xFF) instead -- safely (no crash), but
    via a different path than an SDR-driven "not present" would take, and
    notably a *different* path than this file's other, sibling Sensor
    commands below (which aren't dispatched to a real handler at all --
    see their own comments).
    """
    decoded = send_ipmb_command(bridge, NETFN_SENSOR_EVENT, CMD_GET_SENSOR_READING, data=bytes([SENSOR_NUMBER]))
    assert_completion_code(
        decoded, CC_UNSPECIFIED_ERROR,
        "this board's sensor table is uninitialized -- see this test's docstring"
    )


@not_implemented(
    "Get Sensor Type returns CC_INVALID_CMD (0xC1) -- observed live 2026-08-24, "
    "not yet implemented on this OpenBIC port (unlike its sibling Get Sensor "
    "Reading, which IS dispatched but hits a null-config guard instead)."
)
def test_get_sensor_type(bridge):
    decoded = send_ipmb_command(bridge, NETFN_SENSOR_EVENT, CMD_GET_SENSOR_TYPE, data=bytes([SENSOR_NUMBER]))
    assert_completion_code(decoded, CC_SUCCESS)


@not_implemented(
    "Get Sensor Threshold returns CC_INVALID_CMD (0xC1) -- observed live 2026-08-24, "
    "not yet implemented on this OpenBIC port."
)
def test_get_sensor_threshold(bridge):
    decoded = send_ipmb_command(bridge, NETFN_SENSOR_EVENT, CMD_GET_SENSOR_THRESHOLD, data=bytes([SENSOR_NUMBER]))
    assert_completion_code(decoded, CC_SUCCESS)


@not_implemented(
    "Get Sensor Event Enable returns CC_INVALID_CMD (0xC1) -- observed live 2026-08-24, "
    "not yet implemented on this OpenBIC port."
)
def test_get_sensor_event_enable(bridge):
    decoded = send_ipmb_command(bridge, NETFN_SENSOR_EVENT, CMD_GET_SENSOR_EVENT_ENABLE, data=bytes([SENSOR_NUMBER]))
    assert_completion_code(decoded, CC_SUCCESS)


@not_implemented(
    "Get Sensor Event Status returns CC_INVALID_CMD (0xC1) -- observed live 2026-08-24, "
    "not yet implemented on this OpenBIC port."
)
def test_get_sensor_event_status(bridge):
    decoded = send_ipmb_command(bridge, NETFN_SENSOR_EVENT, CMD_GET_SENSOR_EVENT_STATUS, data=bytes([SENSOR_NUMBER]))
    assert_completion_code(decoded, CC_SUCCESS)
