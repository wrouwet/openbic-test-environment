"""NetFn OEM_1S (0x38): Meta's OEM network function on this platform.

Confirmed with the peer session, 2026-08-24: zero OEM_1S subcommands are
actually implemented here. IPMI_OEM_1S_handler() in plat_stubs.c is a
single unconditional 3-line stub with no dispatch/switch inside it at
all, so CC_INVALID_CMD is the only outcome it can ever produce right now,
for any command byte -- but reaching that stub at all requires clearing
an earlier IANA-prefix gate in ipmi_cmd_handle(), which is its own,
separate, real behavior worth testing on its own terms (see below).
"""

from ipmi_helpers import assert_completion_code, send_ipmb_command
from config import CC_INVALID_CMD, CC_INVALID_IANA, CMD_OEM_ARBITRARY, NETFN_OEM_1S, OEM_IANA_BYTES


def test_oem_command_without_iana_rejected(bridge):
    """OEM NetFn, CMD_OEM_ARBITRARY (0x03, deliberately not the
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
    assert_completion_code(decoded, CC_INVALID_IANA, "no IANA prefix was sent")


def test_oem_command_with_iana_reaches_stub(bridge):
    """OEM NetFn, CMD_OEM_ARBITRARY (0x03), WITH a valid 3-byte IANA
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
    assert_completion_code(decoded, CC_INVALID_CMD, "once past the IANA gate, hits the unconditional OEM stub")
    assert len(decoded["data"]) == 0, f"expected no data from the stub, got {decoded['data'].hex(' ')}"
