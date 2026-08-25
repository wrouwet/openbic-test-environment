"""NetFn App (0x06): universal IPMI commands.

Read-only only, by design -- Cold/Warm Reset, Set ACPI Power State, Set
Watchdog Timer, Set BMC Global Enables etc. are deliberately never
exercised against this live, actively-developed board.
"""

import ipmb
from ipmi_helpers import assert_completion_code, not_implemented, send_ipmb_command
from config import (
    CC_INVALID_CMD,
    CC_SUCCESS,
    CC_UNSPECIFIED_ERROR,
    CHANNEL_THIS_CHANNEL,
    CMD_GET_ACPI_POWER_STATE,
    CMD_GET_BMC_GLOBAL_ENABLES,
    CMD_GET_CHANNEL_INFO,
    CMD_GET_DEVICE_GUID,
    CMD_GET_DEVICE_ID,
    CMD_GET_SELF_TEST_RESULTS,
    CMD_GET_SYSTEM_GUID,
    CMD_GET_WATCHDOG_TIMER,
    NETFN_APP,
    OPENBIC_ADDR,
    OUR_IPMB_ADDR,
    SELF_TEST_EXPECTED_ERROR,
    SELF_TEST_OK_CODES,
)


def test_ipmb_get_device_id_request_accepted(bridge):
    """A well-formed IPMB "Get Device ID" request should be ACKed on the bus.

    This proves the request half of the round trip end-to-end: our IPMB
    framing/checksum is correct, and OpenBIC's I2C target interface (and,
    per manual confirmation against its console log, its IPMB RX/checksum
    validation) accepts it. It does not by itself prove a response was
    sent -- test_ipmb_get_device_id_response below proves that.
    """
    request = ipmb.build_request(
        responder_addr=OPENBIC_ADDR,
        netfn=NETFN_APP,
        requester_addr=OUR_IPMB_ADDR,
        seq=0,
        cmd=CMD_GET_DEVICE_ID,
    )
    print(f"request bytes: {request.hex(' ')}")
    bridge.write(OPENBIC_ADDR, request)  # raises BridgeError on NAK/timeout


def test_ipmb_get_device_id_response(bridge):
    """Send a Get Device ID request and capture + decode OpenBIC's response.

    This was blocked for a while by two real bugs on OpenBIC's side
    (meta-facebook/mcx-n9xx-evk, full-board-port branch), found and fixed
    in direct collaboration with the session developing that firmware:
    responses were initially routed to a fixed address instead of the
    request's actual source address, and after that fix, a deeper Zephyr/
    NXP LPI2C driver issue where a bus registered as both I2C controller
    and target could never actually complete a controller-mode write
    (fixed by pausing/resuming target mode around the write). Confirmed
    working end-to-end 2026-08-24.

    One bridge-side bug surfaced along the way too: a standard Get Device
    ID response with an Auxiliary Firmware Revision field is 22 bytes,
    and the bridge's original 16- and 20-byte capture buffers both
    silently truncated it, dropping the trailing checksum byte and making
    every response look checksum-invalid even once the round trip
    actually worked (see I2C_CMD_MAX_DATA in the bridge's usb_main.c).
    """
    decoded = send_ipmb_command(bridge, NETFN_APP, CMD_GET_DEVICE_ID)
    assert_completion_code(decoded, CC_SUCCESS)


def test_get_self_test_results(bridge):
    """Get Self Test Results (cmd 0x04).

    Response data is 2 bytes: byte 1 is the result code, where 0x55 means
    "no error" and 0x56 means "self test function not implemented" -- both
    are healthy outcomes per the IPMI spec.

    0x57 ("corrupted or inaccessible data or devices") with detail byte
    0x36 is ALSO accepted here, specifically on this board/port -- see
    SELF_TEST_EXPECTED_ERROR's comment in config.py for the full
    explanation (confirmed against source with the peer session): this
    board has no FRU EEPROM physically wired and no SDR table populated
    yet, and APP_GET_SELFTEST_RESULTS() honestly reports both as
    failures. Any *other* result code, or 0x57 with a different detail
    byte, is a real problem and should fail this test.
    """
    decoded = send_ipmb_command(bridge, NETFN_APP, CMD_GET_SELF_TEST_RESULTS)
    assert_completion_code(decoded, CC_SUCCESS)
    assert len(decoded["data"]) >= 1, "expected at least a result-code byte"
    result_code = decoded["data"][0]
    detail_byte = decoded["data"][1] if len(decoded["data"]) >= 2 else None
    detail = f"; second byte (detail): 0x{detail_byte:02x}" if detail_byte is not None else ""

    if result_code in SELF_TEST_OK_CODES:
        return
    expected_code, expected_detail = SELF_TEST_EXPECTED_ERROR
    if result_code == expected_code and detail_byte == expected_detail:
        print(f"self-test result 0x{result_code:02x}/0x{detail_byte:02x} -- "
              f"expected on this board (no FRU EEPROM wired, no SDR table yet)")
        return
    raise AssertionError(
        f"self-test result 0x{result_code:02x} is not one of the healthy "
        f"codes {[hex(c) for c in SELF_TEST_OK_CODES]}, and doesn't match "
        f"the known-expected error 0x{expected_code:02x}/0x{expected_detail:02x} "
        f"either{detail}"
    )


def test_get_device_guid(bridge):
    """Get Device GUID (cmd 0x08).

    Get Device GUID is an *optional* IPMI command -- a compliant BMC/BIC
    is allowed to not implement it, correctly signaled by completion code
    0xC1 (Invalid Command), which is a legitimate response and not a
    malfunction. Confirmed repeatable on this OpenBIC build (2026-08-24):
    it always returns 0xC1 here, so that's accepted as a valid outcome.
    If it's ever implemented, response data should be a 16-byte GUID.
    """
    decoded = send_ipmb_command(bridge, NETFN_APP, CMD_GET_DEVICE_GUID)
    if decoded["completion_code"] == CC_INVALID_CMD:
        print("Get Device GUID not implemented on this platform (0xC1) -- acceptable, it's optional")
        return
    assert_completion_code(decoded, CC_SUCCESS)
    assert len(decoded["data"]) == 16, (
        f"expected a 16-byte GUID, got {len(decoded['data'])} bytes: "
        f"{decoded['data'].hex(' ')}"
    )


def test_get_watchdog_timer(bridge):
    """Get Watchdog Timer (cmd 0x25).

    Confirmed by the peer session that the watchdog is real, working
    infrastructure on this platform (unlike most of the peripheral-level
    stuff below it) -- observed live, 2026-08-24: CC_SUCCESS with an
    8-byte body (timer use, timer actions, pretimeout, expiration flags,
    initial countdown LSB/MSB, present countdown LSB/MSB), currently all
    zero (watchdog not armed/running). Not asserting the data is all-zero
    here -- that's this board's *current* state, not a spec requirement --
    just that the command is genuinely implemented and returns the right
    shape of response, which is the part worth guarding against
    regressing.
    """
    decoded = send_ipmb_command(bridge, NETFN_APP, CMD_GET_WATCHDOG_TIMER)
    assert_completion_code(decoded, CC_SUCCESS, "watchdog is confirmed real, working infrastructure on this platform")
    assert len(decoded["data"]) == 8, (
        f"expected the standard 8-byte Get Watchdog Timer response, got "
        f"{len(decoded['data'])} bytes: {decoded['data'].hex(' ')}"
    )
    print(f"watchdog state: {decoded['data'].hex(' ')}")


def test_get_system_guid_unspecified_error(bridge):
    """Get System GUID (cmd 0x37).

    Confirmed against source with the peer session, 2026-08-24: this is a
    real, genuinely-dispatched handler, not an unimplemented command --
    APP_GET_SYSTEM_GUID() calls get_system_guid() (common/dev/guid.c, the
    generic __weak default, not overridden by this board port), whose
    GUID_FAIL_TO_ACCESS and default cases both map to CC_UNSPECIFIED_ERROR
    (0xFF). There's just no real GUID source wired up on this board, so it
    always falls through to that failure path. Same shape as Get Sensor
    Reading (test_sensor.py): a real handler runs, but this platform has
    nothing behind it yet -- deliberately kept as its own confirmed-
    expected test rather than folded into the generic not_implemented()
    bucket, since 0xFF here means something different (and more specific)
    than the CC_INVALID_CMD (0xC1) that bucket represents.
    """
    decoded = send_ipmb_command(bridge, NETFN_APP, CMD_GET_SYSTEM_GUID)
    assert_completion_code(
        decoded, CC_UNSPECIFIED_ERROR,
        "confirmed against source: real handler, no GUID source wired on this board"
    )


@not_implemented(
    "Get ACPI Power State returns CC_INVALID_CMD (0xC1) -- observed live 2026-08-24, "
    "not yet implemented on this OpenBIC port."
)
def test_get_acpi_power_state(bridge):
    """Get ACPI Power State (cmd 0x07). Read-only; its Set counterpart
    (cmd 0x06) is deliberately never exercised here."""
    decoded = send_ipmb_command(bridge, NETFN_APP, CMD_GET_ACPI_POWER_STATE)
    assert_completion_code(decoded, CC_SUCCESS)


@not_implemented(
    "Get BMC Global Enables returns CC_INVALID_CMD (0xC1) -- observed live 2026-08-24, "
    "not yet implemented on this OpenBIC port."
)
def test_get_bmc_global_enables(bridge):
    """Get BMC Global Enables (cmd 0x2F)."""
    decoded = send_ipmb_command(bridge, NETFN_APP, CMD_GET_BMC_GLOBAL_ENABLES)
    assert_completion_code(decoded, CC_SUCCESS)


@not_implemented(
    "Get Channel Info returns CC_INVALID_CMD (0xC1) -- observed live 2026-08-24, "
    "not yet implemented on this OpenBIC port."
)
def test_get_channel_info(bridge):
    """Get Channel Info (cmd 0x42) for "this channel" (sentinel 0x0E), so
    this test doesn't need to know or guess the platform's real IPMB
    channel number."""
    decoded = send_ipmb_command(bridge, NETFN_APP, CMD_GET_CHANNEL_INFO, data=bytes([CHANNEL_THIS_CHANNEL]))
    assert_completion_code(decoded, CC_SUCCESS)
