"""NetFn Storage (0x0A): SDR (Sensor Data Record) repository commands.

This board's SDR table is genuinely empty (peer-confirmed, 2026-08-24).
"""

from ipmi_helpers import assert_completion_code, not_implemented, send_ipmb_command
from config import CC_SUCCESS, CMD_GET_SDR_REPOSITORY_INFO, CMD_RESERVE_SDR_REPOSITORY, NETFN_STORAGE


def test_reserve_sdr_repository(bridge):
    """Reserve SDR Repository (cmd 0x22).

    Observed live, 2026-08-24: this genuinely works (CC_SUCCESS, hands
    back a real 2-byte reservation ID) even though its sibling Get SDR
    Repository Info below does not. Reservation issuing appears to be
    shared generic infrastructure (also used by the FRU/SEL reservation
    flows) that's wired in regardless of whether the specific repository
    it's reserving space in has any real data behind it yet -- see
    config.py's comment on this asymmetry. Not a fluke; kept as its own
    test rather than assumed to behave like Get SDR Repository Info.
    """
    decoded = send_ipmb_command(bridge, NETFN_STORAGE, CMD_RESERVE_SDR_REPOSITORY)
    assert_completion_code(decoded, CC_SUCCESS, "reservation issuing is real, working infrastructure on this platform")
    assert len(decoded["data"]) == 2, (
        f"expected a 2-byte reservation ID, got {len(decoded['data'])} bytes: {decoded['data'].hex(' ')}"
    )
    print(f"SDR repository reservation ID: {decoded['data'].hex(' ')}")


@not_implemented(
    "Get SDR Repository Info returns CC_INVALID_CMD (0xC1) -- observed live 2026-08-24, "
    "not yet implemented on this OpenBIC port (even though its sibling Reserve SDR "
    "Repository IS implemented -- see this file's module docstring)."
)
def test_get_sdr_repository_info(bridge):
    decoded = send_ipmb_command(bridge, NETFN_STORAGE, CMD_GET_SDR_REPOSITORY_INFO)
    assert_completion_code(decoded, CC_SUCCESS)
