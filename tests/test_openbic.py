"""Incremental tests for the OpenBIC controller reachable through the
USB-to-I2C bridge. Each test builds on the guarantees of the ones before
it: bus presence, then request-level protocol correctness, then full
request/response round trips for a growing set of standard IPMI commands.
"""

import itertools

import ipmb
from config import (
    CMD_GET_DEVICE_GUID,
    CMD_GET_DEVICE_ID,
    CMD_GET_SELF_TEST_RESULTS,
    NETFN_APP,
    OPENBIC_ADDR,
    OUR_IPMB_ADDR,
    SELF_TEST_EXPECTED_ERROR,
    SELF_TEST_OK_CODES,
)

# IPMB's seq field exists precisely so a requester can match a response to
# the request it actually answers, rather than assuming responses arrive
# in order or promptly. That matters here in practice: OpenBIC's response
# path retries for up to ~2.5s internally, so a *stale* response to an
# earlier, unrelated request from a previous test (or even a previous test
# run) can still show up and be captured by a later test's listener if
# every request reuses the same seq. Each call below gets a fresh one
# (6-bit field, so wraps at 64).
_next_seq = itertools.count()


def send_ipmb_command(bridge, netfn, cmd, data=b"", max_drain=3):
    """Build an IPMB request with a fresh sequence number, send it, and
    return the decoded response that actually answers it.

    Shared by every full-round-trip test below. Sends the request once,
    then listens for a response, checking it matches (cmd and seq) before
    accepting it. If a *stale* response to some earlier, unrelated
    request shows up instead -- observed in practice: OpenBIC's queued
    response can persist and get delivered opportunistically well after
    the request that produced it, even across separate test runs, not
    just the immediately following one -- that one's discarded and we
    keep listening (up to max_drain extra attempts) for the real match,
    rather than treating a stale message as a hard failure.
    """
    seq = next(_next_seq) % 64
    request = ipmb.build_request(
        responder_addr=OPENBIC_ADDR,
        netfn=netfn,
        requester_addr=OUR_IPMB_ADDR,
        seq=seq,
        cmd=cmd,
        data=data,
    )
    print(f"request bytes: {request.hex(' ')}")
    bridge.write(OPENBIC_ADDR, request)  # raises BridgeError on NAK/timeout

    for attempt in range(max_drain + 1):
        response = bridge.listen(OUR_IPMB_ADDR)
        print(f"response bytes: {response.hex(' ')}")
        decoded = ipmb.parse_response(response)
        print(f"decoded: {decoded}")
        if decoded["cmd"] == cmd and decoded["seq"] == seq:
            return decoded
        print(f"discarding stale response (cmd=0x{decoded['cmd']:02x} seq={decoded['seq']}) "
              f"that doesn't match ours (cmd=0x{cmd:02x} seq={seq}); still listening...")

    raise AssertionError(
        f"never received a response matching our request (cmd=0x{cmd:02x} seq={seq}) "
        f"after discarding {max_drain + 1} stale/mismatched ones"
    )


def test_detect_openbic(bridge):
    """The OpenBIC controller should respond on the I2C bus."""
    addrs = bridge.scan()
    print(f"bus scan found: {[hex(a) for a in addrs]}")
    assert OPENBIC_ADDR in addrs, (
        f"OpenBIC controller not found at 0x{OPENBIC_ADDR:02x}; "
        f"devices found: {[hex(a) for a in addrs]}"
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
    assert decoded["completion_code"] == 0x00


def test_get_self_test_results(bridge):
    """Get Self Test Results (NetFn App, cmd 0x04).

    Response data is 2 bytes: byte 1 is the result code, where 0x55 means
    "no error" and 0x56 means "self test function not implemented" -- both
    are healthy outcomes per the IPMI spec.

    0x57 ("corrupted or inaccessible data or devices") with detail byte
    0x36 is ALSO accepted here, specifically on this board/port -- see
    SELF_TEST_EXPECTED_ERROR's comment in config.py for the full
    explanation (confirmed against source with the team developing this
    OpenBIC port): this board has no FRU EEPROM physically wired and no
    SDR table populated yet, and APP_GET_SELFTEST_RESULTS() honestly
    reports both as failures. Any *other* result code, or 0x57 with a
    different detail byte, is a real problem and should fail this test.
    """
    decoded = send_ipmb_command(bridge, NETFN_APP, CMD_GET_SELF_TEST_RESULTS)
    assert decoded["completion_code"] == 0x00
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
    """Get Device GUID (NetFn App, cmd 0x08).

    Get Device GUID is an *optional* IPMI command -- a compliant BMC/BIC
    is allowed to not implement it, correctly signaled by completion code
    0xC1 (Invalid Command), which is a legitimate response and not a
    malfunction. Confirmed repeatable on this OpenBIC build (2026-08-24):
    it always returns 0xC1 here, so that's accepted as a valid outcome.
    If it's ever implemented, response data should be a 16-byte GUID.
    """
    decoded = send_ipmb_command(bridge, NETFN_APP, CMD_GET_DEVICE_GUID)
    if decoded["completion_code"] == 0xC1:
        print("Get Device GUID not implemented on this platform (0xC1) -- acceptable, it's optional")
        return
    assert decoded["completion_code"] == 0x00, f"unexpected completion code: 0x{decoded['completion_code']:02x}"
    assert len(decoded["data"]) == 16, (
        f"expected a 16-byte GUID, got {len(decoded['data'])} bytes: "
        f"{decoded['data'].hex(' ')}"
    )
