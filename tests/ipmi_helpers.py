"""Shared plumbing for every IPMI/IPMB test in this suite.

Split out of what used to be one growing test_openbic.py so that adding a
new NetFn's worth of tests (a new test_*.py file) doesn't mean copy-pasting
the request/response round-trip logic again -- this is meant to keep
growing into the full OpenBIC test suite over time, across many files.
"""

import itertools

import pytest

import ipmb
from config import OPENBIC_ADDR, OUR_IPMB_ADDR

# IPMB's seq field exists precisely so a requester can match a response to
# the request it actually answers, rather than assuming responses arrive
# in order or promptly. That matters here in practice: OpenBIC's response
# path retries for up to ~2.5s internally, so a *stale* response to an
# earlier, unrelated request from a previous test (or even a previous test
# run) can still show up and be captured by a later test's listener if
# every request reuses the same seq. This counter is shared across every
# test module that imports it (not per-file), so seq numbers stay globally
# unique for the whole session regardless of which test files ran before
# this one -- a per-file counter would let two different test files each
# start at seq 0 and collide. 6-bit field, so wraps at 64.
_next_seq = itertools.count()


def next_seq():
    return next(_next_seq) % 64


def send_ipmb_command(bridge, netfn, cmd, data=b"", max_drain=3):
    """Build an IPMB request with a fresh sequence number, send it, and
    return the decoded response that actually answers it.

    Shared by every full-round-trip test in this suite. Sends the request
    once, then listens for a response, checking it matches (cmd and seq)
    before accepting it. If a *stale* response to some earlier, unrelated
    request shows up instead -- observed in practice: OpenBIC's queued
    response can persist and get delivered opportunistically well after
    the request that produced it, even across separate test runs, not
    just the immediately following one -- that one's discarded and we
    keep listening (up to max_drain extra attempts) for the real match,
    rather than treating a stale message as a hard failure.
    """
    seq = next_seq()
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


def assert_completion_code(decoded, expected, note=""):
    """Common assertion shape used across the suite, with the observed
    vs. expected byte always spelled out in hex in the failure message."""
    actual = decoded["completion_code"]
    suffix = f" ({note})" if note else ""
    assert actual == expected, (
        f"expected completion code 0x{expected:02x}{suffix}; got 0x{actual:02x}"
    )


def not_implemented(reason):
    """Mark a test as expected to fail because this OpenBIC port doesn't
    implement the command/peripheral it exercises yet.

    This is the mechanism behind this suite's "evolve into the full
    OpenBIC test suite over time" design: tests get written for gaps too,
    not just for what's implemented today, and are deliberately left in
    the suite failing (xfail) rather than skipped or omitted -- so the
    gap shows up every run as a named, tracked test instead of living
    only in a conversation or a separate backlog doc.

    strict=True is deliberate, not an oversight: the moment real support
    lands on the OpenBIC side and this test starts genuinely passing,
    xfail flips to XPASS and the run FAILS loudly -- forcing whoever's
    running the suite to notice and flip this back to a normal test,
    rather than the improvement silently going unnoticed under a
    still-green xfail.

    Always pass a `reason` that says what's actually missing and how it
    was confirmed (source-checked with the peer session, or an observed
    completion code) -- this becomes the de facto backlog/roadmap of
    what OpenBIC still needs, visible directly in test output.
    """
    return pytest.mark.xfail(reason=reason, strict=True)
