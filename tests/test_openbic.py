"""Incremental tests for the OpenBIC controller reachable through the
USB-to-I2C bridge. Each test builds on the guarantees of the ones before
it: bus presence, then request-level protocol correctness, then full
request/response round trips for a growing set of standard IPMI commands.
"""

import itertools

import pytest

import ipmb
from bridge import BridgeError
from config import (
    CC_FRU_DEV_BUSY,
    CC_INVALID_CMD,
    CC_INVALID_IANA,
    CC_UNSPECIFIED_ERROR,
    CMD_GET_DEVICE_GUID,
    CMD_GET_DEVICE_ID,
    CMD_GET_FRU_INVENTORY_AREA_INFO,
    CMD_GET_SELF_TEST_RESULTS,
    CMD_GET_SENSOR_READING,
    CMD_OEM_ARBITRARY,
    CMD_READ_FRU_DATA,
    FRU_ID,
    NETFN_APP,
    NETFN_OEM_1S,
    NETFN_SENSOR_EVENT,
    NETFN_STORAGE,
    OEM_IANA_BYTES,
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


def test_get_sensor_reading_unspecified_error(bridge):
    """Get Sensor Reading (NetFn Sensor/Event, cmd 0x2D) against sensor
    number 1 (arbitrary -- see CC_UNSPECIFIED_ERROR's comment in config.py:
    the value doesn't matter, every sensor number hits the same NULL guard).

    This board has no sensor table populated, so this deliberately does
    NOT expect the "normal" not-configured response (0xCB, "requested
    sensor/record not present"). Confirmed against source with the peer
    session: sensor_init() bails out before allocating sensor_config at
    all, leaving get_sensor_reading() to hit a null-config guard and
    return CC_UNSPECIFIED_ERROR (0xFF) instead -- safely (no crash), but
    via a different path than an SDR-driven "not present" would take.
    """
    decoded = send_ipmb_command(bridge, NETFN_SENSOR_EVENT, CMD_GET_SENSOR_READING, data=bytes([0x01]))
    assert decoded["completion_code"] == CC_UNSPECIFIED_ERROR, (
        f"expected CC_UNSPECIFIED_ERROR (0x{CC_UNSPECIFIED_ERROR:02x}) since this board's sensor "
        f"table is uninitialized; got 0x{decoded['completion_code']:02x}"
    )


def test_get_fru_inventory_area_info(bridge):
    """Get FRU Inventory Area Info (NetFn Storage, cmd 0x10), FRU ID 0.

    Unlike Read FRU Data below, this is a static config lookup
    (find_FRU_size() in fru.c) that never touches the I2C bus, so it
    should succeed even though nothing is physically wired to the FRU
    EEPROM address on this board.
    """
    decoded = send_ipmb_command(bridge, NETFN_STORAGE, CMD_GET_FRU_INVENTORY_AREA_INFO, data=bytes([FRU_ID]))
    assert decoded["completion_code"] == 0x00, f"unexpected completion code: 0x{decoded['completion_code']:02x}"
    assert len(decoded["data"]) >= 2, (
        f"expected at least a 2-byte FRU inventory area size, got {decoded['data'].hex(' ')}"
    )
    print(f"FRU inventory area size bytes: {decoded['data'].hex(' ')}")


def test_read_fru_data_no_eeprom(bridge):
    """Read FRU Data (NetFn Storage, cmd 0x11), FRU ID 0, offset 0, 1 byte.

    Unlike Get FRU Inventory Area Info above, this genuinely calls
    FRU_read() against the real (unwired) FRU EEPROM I2C address -- same
    underlying I2C failure as the Get Self Test Results finding, but
    surfaced here as a specific completion code (CC_FRU_DEV_BUSY, 0x81)
    rather than a raw self-test result byte.
    """
    decoded = send_ipmb_command(
        bridge, NETFN_STORAGE, CMD_READ_FRU_DATA, data=bytes([FRU_ID, 0x00, 0x00, 0x01])
    )
    assert decoded["completion_code"] == CC_FRU_DEV_BUSY, (
        f"expected CC_FRU_DEV_BUSY (0x{CC_FRU_DEV_BUSY:02x}) since no FRU EEPROM is wired up; "
        f"got 0x{decoded['completion_code']:02x}"
    )


def test_oem_command_without_iana_rejected(bridge):
    """OEM NetFn (0x38), CMD_OEM_ARBITRARY (0x03, deliberately not the
    special-cased 0x01/0x02 -- see that constant's comment in config.py),
    with NO data.

    This does NOT reach the platform's OEM_1S stub (IPMI_OEM_1S_handler()
    in plat_stubs.c) at all. Confirmed against source with the peer
    session (took two rounds to get the full picture -- see
    CC_INVALID_IANA's comment in config.py): ipmi_cmd_handle() only
    dispatches to that stub when data_len >= 3 AND the first 3 bytes
    decode as a nonzero IANA enterprise number, since real Meta OEM-1S
    commands are IANA-prefixed by convention. With no data at all that
    gate always fails, landing on a different, earlier rejection:
    CC_INVALID_IANA (0x84). See test_oem_command_with_iana_reaches_stub
    below for the IANA-prefixed case that actually reaches the stub.
    """
    decoded = send_ipmb_command(bridge, NETFN_OEM_1S, CMD_OEM_ARBITRARY)
    assert decoded["completion_code"] == CC_INVALID_IANA, (
        f"expected CC_INVALID_IANA (0x{CC_INVALID_IANA:02x}) since no IANA prefix was sent; "
        f"got 0x{decoded['completion_code']:02x}"
    )


def test_oem_command_with_iana_reaches_stub(bridge):
    """OEM NetFn (0x38), CMD_OEM_ARBITRARY (0x03), WITH a valid 3-byte IANA
    prefix (OEM_IANA_BYTES) plus one arbitrary payload byte -- the
    properly-formed-OEM-1S-frame case that actually clears
    ipmi_cmd_handle()'s IANA gate (see the previous test's docstring) and
    reaches the real, unconditional stub (IPMI_OEM_1S_handler() in
    plat_stubs.c), which doesn't inspect which sub-command was requested
    and should come back as CC_INVALID_CMD (0xC1) with no data.
    """
    decoded = send_ipmb_command(
        bridge, NETFN_OEM_1S, CMD_OEM_ARBITRARY, data=OEM_IANA_BYTES + bytes([0x00])
    )
    assert decoded["completion_code"] == CC_INVALID_CMD, (
        f"expected CC_INVALID_CMD (0x{CC_INVALID_CMD:02x}) from the unconditional OEM stub "
        f"once past the IANA gate; got 0x{decoded['completion_code']:02x}"
    )
    assert len(decoded["data"]) == 0, f"expected no data from the stub, got {decoded['data'].hex(' ')}"


def test_corrupted_message_checksum_silently_dropped(bridge):
    """A request with a valid header checksum but a corrupted trailing
    (message/data) checksum should get no response at all.

    Confirmed against source with the peer session: IPMB_RXTask()'s
    validate_checksum() failing for *either* reason (header or message
    checksum) takes the exact same `goto cleanup` path after just an
    LOG_ERR -- both failure modes are observably identical on the wire
    (silently dropped), so this test can't distinguish which checksum
    failed from the response side; only the OpenBIC console log can, and
    we don't have visibility into that from here.

    We still expect the *write itself* to succeed (bridge.write() ACKs
    at the I2C level; checksum validation happens afterward, in
    software), and then either no response at all (the expected case:
    bridge.listen() raises, since the on-device "L" listen times out and
    reports it as an error, not a response) or -- to guard against a
    flaky false pass -- some genuinely unrelated stale response left
    over from an earlier test's request, which is fine as long as it
    doesn't actually match cmd+seq of *this* corrupted request.
    """
    seq = next(_next_seq) % 64
    request = bytearray(
        ipmb.build_request(
            responder_addr=OPENBIC_ADDR,
            netfn=NETFN_APP,
            requester_addr=OUR_IPMB_ADDR,
            seq=seq,
            cmd=CMD_GET_DEVICE_ID,
        )
    )
    request[-1] ^= 0xFF  # flip every bit of the trailing message checksum byte; header checksum (index 1) untouched
    request = bytes(request)
    print(f"request bytes (deliberately corrupted message checksum): {request.hex(' ')}")
    bridge.write(OPENBIC_ADDR, request)  # the I2C-level write itself should still succeed

    try:
        response = bridge.listen(OUR_IPMB_ADDR)
    except BridgeError as exc:
        print(f"no response arrived, as expected for a checksum failure: {exc}")
        return

    decoded = ipmb.parse_response(response)
    print(f"received a response anyway: {decoded}")
    assert not (decoded["cmd"] == CMD_GET_DEVICE_ID and decoded["seq"] == seq), (
        "got a real response matching our deliberately-corrupted request -- "
        "OpenBIC's message checksum validation isn't rejecting it as expected"
    )
    print("that response doesn't match this request's cmd+seq, so it's an unrelated "
          "stale response from something else -- still consistent with our corrupted "
          "request having been silently dropped")


def test_back_to_back_requests_queue_depth(bridge):
    """Documents a known constraint rather than asserting a single "correct"
    behavior: OpenBIC's outbound IPMB path has only a 1-deep TX queue.

    Confirmed against source with the peer session: the inbound I2C
    target receive queue (ipmb_target_msgq) is 2-deep, so firing two
    requests back-to-back is usually fine on the way in -- both get
    received and dispatched. But if one request's response tries to
    enqueue while the other's is still occupying the 1-deep
    ipmb_txqueue (e.g. still mid-retry -- notably, our own bridge isn't
    even listening yet at that point, since it only switches into
    slave/capture mode after both writes are sent, which likely biases
    which one is mid-retry when the collision happens), it fails to
    enqueue and is silently dropped -- logged on OpenBIC's console
    ("IPMI_handler send IPMB resp fail status: 2", eventually "Reach the
    MAX retry times...") but with *zero* wire-level indication to us: it
    looks exactly like that request was never received at all.

    Confirmed live: this is a genuine race and does NOT reliably favor
    request 1 -- a real run observed request 2's response arriving while
    request 1's never did, the opposite of a naive "first come, first
    served" assumption. So we only assert the one thing actually
    guaranteed by a 1-deep TX queue (at least one response gets through)
    and print whatever pattern actually happened, rather than asserting
    which specific one wins -- asserting an ordering here would make the
    test flaky against real queue/retry timing instead of describing the
    actual constraint.

    There's an even sharper version of this race, also confirmed live:
    OpenBIC can start driving the bus as master to send request 1's
    response before we've finished writing request 2 out (we don't wait
    in between -- that's the point of this test), which collides on the
    physical bus and makes request 2's own bridge.write() fail with
    "arbitration lost" rather than the request quietly landing in the
    2-deep RX queue. That's not a bridge or framing bug -- multi-master
    I2C is supposed to detect exactly this and back off -- so it's
    handled here as a valid (if more extreme) outcome of the same
    underlying single-response-in-flight constraint, not treated as a
    hard failure.
    """
    seq1 = next(_next_seq) % 64
    seq2 = next(_next_seq) % 64
    req1 = ipmb.build_request(OPENBIC_ADDR, NETFN_APP, OUR_IPMB_ADDR, seq1, CMD_GET_DEVICE_ID)
    req2 = ipmb.build_request(OPENBIC_ADDR, NETFN_APP, OUR_IPMB_ADDR, seq2, CMD_GET_DEVICE_ID)
    print(f"request 1 (seq={seq1}): {req1.hex(' ')}")
    print(f"request 2 (seq={seq2}): {req2.hex(' ')}")
    bridge.write(OPENBIC_ADDR, req1)
    try:
        bridge.write(OPENBIC_ADDR, req2)
    except BridgeError as exc:
        print(f"request 2's write itself lost the bus race against OpenBIC's own outbound "
              f"response for request 1 ({exc}) -- an even more direct demonstration of this "
              f"port's single-response-in-flight constraint, at the physical bus level rather "
              f"than the software TX queue. Only request 1 actually made it out; expecting "
              f"just its response below.")
        seq2 = None  # never actually sent; don't expect (or even look for) its response

    expected_seqs = {s for s in (seq1, seq2) if s is not None}
    seen = {}
    for attempt in range(4):
        try:
            response = bridge.listen(OUR_IPMB_ADDR)
        except BridgeError as exc:
            print(f"listen attempt {attempt + 1}: no (more) responses arrived ({exc})")
            break
        decoded = ipmb.parse_response(response)
        print(f"listen attempt {attempt + 1}: got {decoded}")
        if decoded["cmd"] == CMD_GET_DEVICE_ID and decoded["seq"] in expected_seqs:
            seen[decoded["seq"]] = decoded
        if len(seen) == len(expected_seqs):
            break

    assert len(seen) >= 1, (
        "neither request's response arrived at all -- if this fails, something more "
        "serious than the known 1-deep-queue constraint is going on (a 1-deep queue "
        "should still let at least one response through)"
    )
    if len(seen) == len(expected_seqs):
        print(f"all {len(expected_seqs)} expected response(s) arrived -- "
              f"no queue collision occurred this run")
    else:
        missing = expected_seqs - seen.keys()
        print(f"response(s) for seq={sorted(missing)} never arrived -- black-holed by the "
              f"1-deep TX queue (seq={sorted(seen)} made it through) -- known constraint, "
              f"not a bug, and not guaranteed to always be the same one (see this test's "
              f"docstring)")
