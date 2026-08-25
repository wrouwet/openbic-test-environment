"""Incremental tests for the OpenBIC controller reachable through the
USB-to-I2C bridge. Each test builds on the guarantees of the ones before
it: bus presence, then request-level protocol correctness, then (once
unblocked -- see the xfail below) full request/response round trips.
"""

import ipmb
from config import CMD_GET_DEVICE_ID, NETFN_APP, OPENBIC_ADDR, OUR_IPMB_ADDR


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
    validation) accepts it. It does not prove a response was sent -- see
    test_ipmb_get_device_id_response below for why that's a separate,
    currently-failing step.
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
    request = ipmb.build_request(
        responder_addr=OPENBIC_ADDR,
        netfn=NETFN_APP,
        requester_addr=OUR_IPMB_ADDR,
        seq=0,
        cmd=CMD_GET_DEVICE_ID,
    )
    response = bridge.ipmb_request(OPENBIC_ADDR, OUR_IPMB_ADDR, request)
    print(f"response bytes: {response.hex(' ')}")

    decoded = ipmb.parse_response(response)
    print(f"decoded: {decoded}")
    assert decoded["completion_code"] == 0x00
    assert decoded["cmd"] == CMD_GET_DEVICE_ID
