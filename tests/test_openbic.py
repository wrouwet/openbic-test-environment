"""Incremental tests for the OpenBIC controller reachable through the
USB-to-I2C bridge. Each test builds on the guarantees of the ones before
it: bus presence, then request-level protocol correctness, then (once
unblocked -- see the xfail below) full request/response round trips.
"""

import pytest

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


@pytest.mark.xfail(
    reason=(
        "OpenBIC (meta-facebook/mcx-n9xx-evk, full-board-port branch) always "
        "sends IPMB responses to a fixed ipmb_cfg.channel_target_address "
        "(hardcoded to its own address, 0x20, in this port's plat_ipmb.c) "
        "instead of routing to the request's actual src_addr. It will never "
        "write a response to our requester address until that's fixed "
        "upstream in common/service/ipmb/ipmb.c. Confirmed 2026-08-24 in "
        "direct collaboration with the session developing that firmware."
    ),
    strict=True,
)
def test_ipmb_get_device_id_response(bridge):
    """Send a Get Device ID request and capture OpenBIC's response.

    strict=True: once OpenBIC's response routing is fixed upstream, this
    test starts *passing*, which pytest will report as an "unexpected
    pass" (XPASS) failure -- a deliberate tripwire so we notice the fix
    landed instead of leaving a stale xfail in place.
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
