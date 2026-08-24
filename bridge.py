"""Python client for the FRDM-MCXA153 USB-to-I2C bridge firmware.

See https://github.com/wrouwet/frdm-mcxa153-usb-i2c-hub for the bridge
firmware itself. Talks to its USB CDC virtual COM port using its text
command protocol:

    S                                -> OK <addr> <addr> ...
    W <addr> <byte> [byte ...]       -> OK
    R <addr> <n>                     -> OK <byte> [byte ...]
    X <addr> <n> <byte> [byte ...]   -> OK <byte> [byte ...]
    I <addr> <ourAddr> <byte> ...    -> OK <byte> [byte ...]

Auto-detects the right serial port by USB VID:PID rather than assuming
a fixed /dev/ttyACM number -- the bridge board's MCU-Link debug probe
exposes its own, unrelated ttyACM device, and which one gets which
number depends on enumeration order (a debug probe reconnecting can
swap them), not a fixed identity.
"""

import time

import serial
from serial.tools import list_ports

USB_VID = 0x1FC9
USB_PID = 0x0094
USB_PRODUCT = "MCU VIRTUAL COM DEMO"

BAUDRATE = 115200
# The bridge's "I" command (ipmb_request below) can itself wait several
# seconds on-device for a slave-mode response before giving up, so the
# host-side serial read timeout has to comfortably exceed that.
DEFAULT_TIMEOUT_S = 6.0


class BridgeError(Exception):
    """Raised when the bridge reports an error or doesn't respond."""


def find_port():
    """Return the device path of the FRDM-MCXA153 USB-to-I2C hub's CDC port."""
    for p in list_ports.comports():
        if p.vid == USB_VID and p.pid == USB_PID:
            return p.device
    raise BridgeError(
        f"No FRDM-MCXA153 USB-I2C hub found (looking for USB VID:PID "
        f"{USB_VID:04x}:{USB_PID:04x}, '{USB_PRODUCT}'). Is it plugged in?"
    )


class I2CBridge:
    """A connection to the board's I2C bridge firmware."""

    def __init__(self, port=None, timeout=DEFAULT_TIMEOUT_S):
        self.port = port or find_port()
        self.ser = serial.Serial(self.port, baudrate=BAUDRATE, timeout=timeout)
        # Give the CDC control-line-state handshake (DTR) a moment to land
        # before the firmware will start accepting commands.
        time.sleep(0.3)

    def close(self):
        self.ser.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        self.close()

    def _command(self, line):
        self.ser.reset_input_buffer()
        self.ser.write((line + "\r\n").encode("ascii"))
        raw = self.ser.readline()
        if not raw:
            raise BridgeError(f"no response from bridge to command {line!r} "
                               f"(timed out after {self.ser.timeout}s)")
        return raw.decode("ascii", errors="replace").strip()

    @staticmethod
    def _split_ok(reply, what):
        parts = reply.split()
        if not parts or parts[0] != "OK":
            raise BridgeError(f"{what}: {reply}")
        return parts[1:]

    def scan(self):
        """Scan the I2C bus. Returns a sorted list of 7-bit addresses that ACKed."""
        parts = self._split_ok(self._command("S"), "bus scan failed")
        return sorted(int(x, 16) for x in parts)

    def probe(self, addr):
        """Return True if a device at the given 7-bit address ACKs."""
        return addr in self.scan()

    def write(self, addr, data):
        """Write bytes (an iterable of ints 0-255) to the given address."""
        payload = " ".join(f"{b:02x}" for b in data)
        cmd = f"W {addr:02x} {payload}".strip()
        reply = self._command(cmd)
        if reply != "OK":
            raise BridgeError(f"write to 0x{addr:02x} failed: {reply}")

    def read(self, addr, n):
        """Read n bytes from the given address. Returns bytes."""
        parts = self._split_ok(self._command(f"R {addr:02x} {n}"),
                                f"read from 0x{addr:02x} failed")
        return bytes(int(x, 16) for x in parts)

    def write_read(self, addr, data, n):
        """Write bytes, repeated-start, then read n bytes (register-read pattern)."""
        payload = " ".join(f"{b:02x}" for b in data)
        cmd = f"X {addr:02x} {n} {payload}".strip()
        parts = self._split_ok(self._command(cmd),
                                f"write_read to 0x{addr:02x} failed")
        return bytes(int(x, 16) for x in parts)

    def ipmb_request(self, addr, our_addr, payload):
        """Write an IPMB-framed payload to addr, then briefly become an I2C
        slave at our_addr and capture whatever addr writes back.

        This exists because some I2C targets (e.g. IPMB devices like
        OpenBIC) don't respond by being read from -- they respond by
        becoming bus master themselves and writing the response out to
        the address the request named as the requester. Returns the
        captured response bytes (see ipmb.parse_response() to decode).
        """
        hexstr = " ".join(f"{b:02x}" for b in payload)
        cmd = f"I {addr:02x} {our_addr:02x} {hexstr}".strip()
        parts = self._split_ok(self._command(cmd),
                                f"ipmb_request to 0x{addr:02x} failed")
        return bytes(int(x, 16) for x in parts)
