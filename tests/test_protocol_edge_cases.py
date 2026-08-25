"""Protocol-layer edge cases that aren't specific to any one NetFn:
malformed framing, and IPMB's outbound-queue depth under contention.
"""

import ipmb
from bridge import BridgeError
from ipmi_helpers import next_seq
from config import CMD_GET_DEVICE_ID, NETFN_APP, OPENBIC_ADDR, OUR_IPMB_ADDR


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
    seq = next_seq()
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
    seq1 = next_seq()
    seq2 = next_seq()
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
