"""IPMB (Intelligent Platform Management Bus) request framing.

Builds the byte payload for an IPMB request, *excluding* the physical I2C
address byte -- that's handled separately by the bridge's own addressing
(the `<addr>` argument to its W/R/X/I commands), matching how a real IPMB
frame's "Byte 1" (responder address) is redundant with the wire-level
address+R/W byte already sent by the I2C hardware.

Layout of the bytes this module produces (i.e. IPMB frame bytes 2-7):

    NetFn(6b)|rsLUN(2b), header checksum,
    requester addr<<1, seq(6b)|rqLUN(2b), command, data..., data checksum

Checksum is the standard IPMI 2's-complement 8-bit checksum: the sum of
the covered bytes, plus the checksum byte itself, is 0 mod 256.
"""


def checksum(data):
    """2's-complement checksum such that sum(data) + checksum(data) == 0 mod 256."""
    return (-sum(data)) & 0xFF


def build_request(responder_addr, netfn, requester_addr, seq, cmd, data=b"", lun=0, requester_lun=0):
    """Build an IPMB request (see module docstring for the exact byte layout).

    responder_addr, requester_addr: 7-bit I2C addresses (not pre-shifted).
    netfn: 6-bit network function code (e.g. 0x06 for App).
    seq: 6-bit sequence number, used to match a response to this request.
    cmd: the IPMI command byte.
    data: optional command-specific data bytes.
    """
    byte1 = (responder_addr << 1) & 0xFF
    byte2 = ((netfn & 0x3F) << 2) | (lun & 0x3)
    header_checksum = checksum([byte1, byte2])

    byte4 = (requester_addr << 1) & 0xFF
    byte5 = ((seq & 0x3F) << 2) | (requester_lun & 0x3)
    tail = bytes([byte4, byte5, cmd]) + bytes(data)
    data_checksum = checksum(tail)

    return bytes([byte2, header_checksum]) + tail + bytes([data_checksum])


def parse_response(payload):
    """Parse a captured IPMB response payload (as returned by a slave-mode
    capture, i.e. also missing the initial responder-address wire byte).

    Returns a dict with the decoded fields, including 'completion_code' and
    any trailing 'data' bytes. Raises ValueError if too short or a checksum
    doesn't match.
    """
    if len(payload) < 6:
        raise ValueError(f"IPMB response too short: {len(payload)} bytes")

    netfn_lun, header_checksum, requester_byte, seq_lun, cmd, completion_code = payload[:6]
    data = payload[6:-1]
    data_checksum = payload[-1]

    if checksum([requester_byte, seq_lun, cmd, completion_code, *data]) != data_checksum:
        raise ValueError("IPMB response data checksum mismatch")

    return {
        "netfn": (netfn_lun >> 2) & 0x3F,
        "lun": netfn_lun & 0x3,
        "requester_addr": requester_byte >> 1,
        "seq": (seq_lun >> 2) & 0x3F,
        "cmd": cmd,
        "completion_code": completion_code,
        "data": bytes(data),
    }
