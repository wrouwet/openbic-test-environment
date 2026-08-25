"""NetFn Storage (0x0A): SEL (System Event Log) commands.

Unlike SDR's Reserve/Info split (see test_storage_sdr.py), all three SEL
commands probed here -- including Reserve SEL, the direct sibling of the
SDR reservation call that DOES work -- were observed to return
CC_INVALID_CMD. So SEL support on this platform isn't just "the data
tables are empty", it's "no SEL command has a handler wired in at all
yet", a strictly earlier stage than SDR/FRU.
"""

from ipmi_helpers import assert_completion_code, not_implemented, send_ipmb_command
from config import CC_SUCCESS, CMD_GET_SEL_INFO, CMD_GET_SEL_TIME, CMD_RESERVE_SEL, NETFN_STORAGE


@not_implemented(
    "Get SEL Info returns CC_INVALID_CMD (0xC1) -- observed live 2026-08-24, "
    "not yet implemented on this OpenBIC port."
)
def test_get_sel_info(bridge):
    decoded = send_ipmb_command(bridge, NETFN_STORAGE, CMD_GET_SEL_INFO)
    assert_completion_code(decoded, CC_SUCCESS)


@not_implemented(
    "Reserve SEL returns CC_INVALID_CMD (0xC1) -- observed live 2026-08-24, not yet "
    "implemented, notably UNLIKE its direct sibling Reserve SDR Repository (see "
    "test_storage_sdr.py), which does work -- so this isn't the same shared "
    "reservation infrastructure being reused for SEL."
)
def test_reserve_sel(bridge):
    decoded = send_ipmb_command(bridge, NETFN_STORAGE, CMD_RESERVE_SEL)
    assert_completion_code(decoded, CC_SUCCESS)


@not_implemented(
    "Get SEL Time returns CC_INVALID_CMD (0xC1) -- observed live 2026-08-24, "
    "not yet implemented on this OpenBIC port."
)
def test_get_sel_time(bridge):
    decoded = send_ipmb_command(bridge, NETFN_STORAGE, CMD_GET_SEL_TIME)
    assert_completion_code(decoded, CC_SUCCESS)
