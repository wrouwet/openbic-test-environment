"""NetFn Storage (0x0A): FRU inventory commands.

This board has a single FRU (FRU_ID 0) pointed at a real I2C EEPROM
address with nothing physically wired to it (peer-confirmed, 2026-08-24).
"""

from ipmi_helpers import assert_completion_code, send_ipmb_command
from config import (
    CC_FRU_DEV_BUSY,
    CC_SUCCESS,
    CMD_GET_FRU_INVENTORY_AREA_INFO,
    CMD_READ_FRU_DATA,
    FRU_ID,
    NETFN_STORAGE,
)


def test_get_fru_inventory_area_info(bridge):
    """Get FRU Inventory Area Info (cmd 0x10), FRU ID 0.

    Unlike Read FRU Data below, this is a static config lookup
    (find_FRU_size() in fru.c) that never touches the I2C bus, so it
    should succeed even though nothing is physically wired to the FRU
    EEPROM address on this board.
    """
    decoded = send_ipmb_command(bridge, NETFN_STORAGE, CMD_GET_FRU_INVENTORY_AREA_INFO, data=bytes([FRU_ID]))
    assert_completion_code(decoded, CC_SUCCESS)
    assert len(decoded["data"]) >= 2, (
        f"expected at least a 2-byte FRU inventory area size, got {decoded['data'].hex(' ')}"
    )
    print(f"FRU inventory area size bytes: {decoded['data'].hex(' ')}")


def test_read_fru_data_no_eeprom(bridge):
    """Read FRU Data (cmd 0x11), FRU ID 0, offset 0, 1 byte.

    Unlike Get FRU Inventory Area Info above, this genuinely calls
    FRU_read() against the real (unwired) FRU EEPROM I2C address -- same
    underlying I2C failure as the Get Self Test Results finding, but
    surfaced here as a specific completion code (CC_FRU_DEV_BUSY, 0x81)
    rather than a raw self-test result byte.
    """
    decoded = send_ipmb_command(
        bridge, NETFN_STORAGE, CMD_READ_FRU_DATA, data=bytes([FRU_ID, 0x00, 0x00, 0x01])
    )
    assert_completion_code(decoded, CC_FRU_DEV_BUSY, "no FRU EEPROM is physically wired up on this board")
