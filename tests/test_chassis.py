"""NetFn Chassis (0x00).

Read-only only, by design -- Chassis Control (power on/off/cycle) and
Chassis Reset are deliberately never exercised here: they would actually
power-cycle or reset the real board.

All three commands here were observed live (2026-08-24) to return
CC_INVALID_CMD (0xC1). That's a meaningful, positive data point in its
own right, not just "nothing to see": it confirms the Chassis NetFn IS
recognized and dispatched on this platform (a genuinely-unrecognized
NetFn would look different -- see test_protocol_edge_cases.py's checksum
test for what "not even dispatched" looks like: no response at all), it's
just that no individual Chassis command has a real handler wired in yet.
Tracked here as this suite's OpenBIC-development backlog for Chassis
support, per the peer session's confirmation that nothing chassis-related
is implemented on this EVK port yet.
"""

from ipmi_helpers import assert_completion_code, not_implemented, send_ipmb_command
from config import (
    CC_SUCCESS,
    CMD_GET_CHASSIS_STATUS,
    CMD_GET_POH_COUNTER,
    CMD_GET_SYSTEM_RESTART_CAUSE,
    NETFN_CHASSIS,
)


@not_implemented(
    "Get Chassis Status returns CC_INVALID_CMD (0xC1) -- observed live 2026-08-24, "
    "not yet implemented on this OpenBIC port."
)
def test_get_chassis_status(bridge):
    decoded = send_ipmb_command(bridge, NETFN_CHASSIS, CMD_GET_CHASSIS_STATUS)
    assert_completion_code(decoded, CC_SUCCESS)


@not_implemented(
    "Get System Restart Cause returns CC_INVALID_CMD (0xC1) -- observed live 2026-08-24, "
    "not yet implemented on this OpenBIC port."
)
def test_get_system_restart_cause(bridge):
    decoded = send_ipmb_command(bridge, NETFN_CHASSIS, CMD_GET_SYSTEM_RESTART_CAUSE)
    assert_completion_code(decoded, CC_SUCCESS)


@not_implemented(
    "Get POH Counter returns CC_INVALID_CMD (0xC1) -- observed live 2026-08-24, "
    "not yet implemented on this OpenBIC port."
)
def test_get_poh_counter(bridge):
    decoded = send_ipmb_command(bridge, NETFN_CHASSIS, CMD_GET_POH_COUNTER)
    assert_completion_code(decoded, CC_SUCCESS)
