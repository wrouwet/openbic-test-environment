"""Python client for the FRDM-MCXA153 USB-to-I2C bridge firmware.

See https://github.com/wrouwet/frdm-mcxa153-usb-i2c-hub for the bridge
firmware itself. Talks to its USB CDC virtual COM port using its text
command protocol:

    S                                -> OK <addr> <addr> ...
    W <addr> <byte> [byte ...]       -> OK
    R <addr> <n>                     -> OK <byte> [byte ...]
    X <addr> <n> <byte> [byte ...]   -> OK <byte> [byte ...]
    I <addr> <ourAddr> <byte> ...    -> OK <byte> [byte ...]
    L <ourAddr>                      -> OK <byte> [byte ...]

Auto-detects the right serial port by USB VID:PID rather than assuming
a fixed /dev/ttyACM number -- the bridge board's MCU-Link debug probe
exposes its own, unrelated ttyACM device, and which one gets which
number depends on enumeration order (a debug probe reconnecting can
swap them), not a fixed identity. This bit us for real during
development: a stretch of "the bridge stopped responding to anything"
turned out to be nothing more than that swap happening mid-session.

Verbose by design (see VERBOSE / _log() below): most of the real bugs
found while building this suite -- the IPMB response-routing bug, the
LPI2C controller/target driver hang, this bridge's own reply-buffer
truncation, stale queued responses from earlier requests -- were only
findable at all because we could see exactly what went out and came
back on the wire, and when, rather than a bare "it timed out". Printing
too much here is a deliberate trade against ever again staring at a
generic timeout and having to guess.
"""

import sys
import time

import serial
from serial.tools import list_ports

try:
    import termios
    # termios.error is a plain Exception, *not* an OSError subclass (which
    # is what you'd expect from a low-level POSIX errno-style failure).
    # Found this by actually killing the link mid-command in testing:
    # reset_input_buffer() on a dead fd raises termios.error, and a bare
    # `except OSError` silently missed it, leaving the client hung instead
    # of reconnecting. Windows has no termios module at all, hence the
    # guarded import and the fallback tuple below.
    _LINK_BROKEN_EXCEPTIONS = (serial.SerialException, OSError, termios.error)
except ImportError:
    _LINK_BROKEN_EXCEPTIONS = (serial.SerialException, OSError)

USB_VID = 0x1FC9
USB_PID = 0x0094
USB_PRODUCT = "MCU VIRTUAL COM DEMO"

BAUDRATE = 115200

# The bridge's "I"/"L" commands can themselves wait several seconds
# on-device (in slave-mode, listening for a target that responds by
# becoming bus master and writing back to us -- see ipmb_request()'s
# docstring) before giving up, so the host-side serial read timeout has
# to comfortably exceed that, or we'd time out on our side before the
# bridge even reports its own timeout.
DEFAULT_TIMEOUT_S = 6.0

# "ERR busy" from the bridge is a *transient* condition worth retrying,
# not a real failure -- unlike "ERR nak" (nothing at that address) or a
# parse error, which are real answers returned immediately. In practice
# this shows up because OpenBIC's own IPMB response path retries
# internally for up to ~2.5s (a fixed 5 attempts, 500ms apart, tied to
# its single-slot response queue), and issuing our next request before
# that settles can find the bus still busy from the tail end of it. The
# retry budget here needs real margin beyond that 2.5s, not just barely
# covering it, because our own retries add latency that can itself run
# into OpenBIC's *next* window if we're unlucky.
BUSY_RETRIES = 6
BUSY_RETRY_DELAY_S = 1.0

# How long to keep looking for the bridge to reappear after the serial
# link itself breaks (as opposed to a normal in-protocol error like a NAK
# or busy) -- e.g. the board resets (a reflash, a watchdog, a manual
# power cycle) and its USB re-enumerates, possibly under a different
# /dev/ttyACM path. 15s comfortably covers a full MCXA153 boot + USB
# CDC re-enumeration + the firmware's own ~0.3s DTR settle, with margin.
RECONNECT_TIMEOUT_S = 15.0
RECONNECT_POLL_S = 0.5

# Once physically reconnected, retry the *command* itself this many
# times -- covers "reconnected to the port, but the board's firmware is
# still mid-boot and not yet accepting commands" (which looks like a
# fresh, separate failure rather than a broken link, since the port
# genuinely opened fine that time).
RECONNECT_COMMAND_RETRIES = 2

# See _log(): flip to False to quiet the wire-level trace. Left on by
# default because "what exactly happened on the wire" is what actually
# resolved every hard bug found while building this suite -- a quiet
# client would have just reported "timeout" and left us guessing.
VERBOSE = True


def _log(msg):
    if VERBOSE:
        print(f"[bridge] {msg}", file=sys.stderr)


class BridgeError(Exception):
    """Raised when the bridge reports an error or doesn't respond."""


class BridgeDisconnected(BridgeError):
    """The bridge's serial link is gone and didn't come back in time.

    Deliberately a distinct type from a plain BridgeError (an in-protocol
    failure like a NAK, or a normal command timeout with the link still
    up) so callers -- and test reports -- can immediately tell "the board
    is actually gone" apart from "the board answered, just not the way we
    wanted". Without this split, both looked identical from a test's
    perspective (some exception, some timeout-shaped message), which is
    exactly the ambiguity that cost time during development.
    """


def find_port():
    """Return the device path of the FRDM-MCXA153 USB-to-I2C hub's CDC port.

    Always re-scans live rather than caching a path, specifically so a
    reconnect after the device re-enumerates under a new /dev/ttyACM
    number picks up the new one automatically.
    """
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
        # None here means "auto-detect by VID:PID, and re-detect on every
        # reconnect too" -- the common case, and the only mode that's
        # actually robust to the device's /dev/ttyACM number changing.
        # An explicit port is honored as-is even across reconnects, on
        # the assumption that if you asked for a specific path you meant
        # it (e.g. a fixed symlink), but note that won't survive a real
        # renumbering the way auto-detect does.
        self.explicit_port = port
        self.timeout = timeout
        self.port = port or find_port()
        _log(f"connecting to {self.port} at {BAUDRATE} baud")
        self.ser = serial.Serial(self.port, baudrate=BAUDRATE, timeout=timeout)
        self._settle()

    def _settle(self):
        # Give the CDC control-line-state handshake (DTR) a moment to land
        # before the firmware will start accepting commands -- opening the
        # serial port doesn't mean the firmware's USB stack has processed
        # the "port opened" event yet. Needed both on first connect and
        # after every reconnect; skipping it was an intermittent source
        # of a spurious first-command failure early in development.
        time.sleep(0.3)

    def close(self):
        self.ser.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        self.close()

    def _still_enumerated(self):
        """Best-effort check of whether *some* bridge is still visible on
        the USB bus at all, purely to make a plain command timeout's
        error message more useful. Doesn't confirm it's specifically the
        device at self.port -- just whether "it's probably unplugged" is
        a plausible explanation for the silence, versus "it's plugged in
        but just not answering" (a more concerning, different problem)."""
        try:
            find_port()
            return True
        except BridgeError:
            return False

    def _reconnect(self):
        """Wait for the bridge to (re)appear and open a fresh connection to it.

        Called when the serial link itself has broken (as opposed to a
        normal in-protocol error) -- typically because the board reset
        and its USB re-enumerated, possibly under a different
        /dev/ttyACM path (see find_port()'s live re-scan; a fixed
        explicit port, if one was given to __init__, is retried as-is
        instead of re-detected -- see explicit_port's comment above).

        Raises BridgeDisconnected if the bridge doesn't reappear within
        RECONNECT_TIMEOUT_S -- a clear, distinct signal that this looks
        like the board is actually gone/powered off, not just mid-reboot.
        """
        _log("link broken -- closing old handle and waiting for the bridge to reappear")
        try:
            self.ser.close()
        except Exception:
            pass  # already broken in whatever way triggered this; ignore

        start = time.monotonic()
        deadline = start + RECONNECT_TIMEOUT_S
        last_error = None
        poll_count = 0
        while time.monotonic() < deadline:
            poll_count += 1
            try:
                port = self.explicit_port or find_port()
                _log(f"reconnect poll #{poll_count}: found {port}, opening...")
                self.ser = serial.Serial(port, baudrate=BAUDRATE, timeout=self.timeout)
                self.port = port
                self._settle()
                _log(f"reconnected to {port} after {time.monotonic() - start:.1f}s")
                return
            except (BridgeError, *_LINK_BROKEN_EXCEPTIONS) as exc:
                last_error = exc
                _log(f"reconnect poll #{poll_count}: not yet ({exc}); "
                     f"retrying in {RECONNECT_POLL_S}s")
                time.sleep(RECONNECT_POLL_S)

        raise BridgeDisconnected(
            f"bridge did not reappear within {RECONNECT_TIMEOUT_S}s of the "
            f"serial link breaking (last error: {last_error}) -- is the "
            f"board actually unplugged/powered off, rather than just resetting?"
        )

    def _command(self, line, retries=BUSY_RETRIES):
        """Send one command and return the raw reply line.

        Two independent layers of resilience here, both transparent to
        callers -- they just see either a reply or a raised BridgeError/
        BridgeDisconnected, never the retrying/reconnecting itself:

        - Retries on "ERR busy" (see BUSY_RETRIES' comment for why this
          is transient rather than a real failure).
        - If the serial link itself breaks partway through (one of
          _LINK_BROKEN_EXCEPTIONS -- e.g. the board reset and its USB
          re-enumerated under a new path), reconnects via _reconnect()
          and retries the *command* a bounded number of times, rather
          than raising immediately or hanging forever on a dead fd.
        """
        for reconnect_attempt in range(RECONNECT_COMMAND_RETRIES + 1):
            try:
                for attempt in range(retries + 1):
                    t0 = time.monotonic()
                    self.ser.reset_input_buffer()
                    self.ser.write((line + "\r\n").encode("ascii"))
                    _log(f"-> {line!r}")
                    raw = self.ser.readline()
                    elapsed = time.monotonic() - t0
                    if not raw:
                        still_present = self._still_enumerated()
                        status = ("still enumerated, just didn't answer in time"
                                  if still_present else
                                  "no longer enumerated -- looks disconnected")
                        _log(f"<- (no reply after {elapsed:.1f}s; {status})")
                        raise BridgeError(
                            f"no response from bridge to command {line!r} "
                            f"(timed out after {self.ser.timeout}s; {status})"
                        )
                    reply = raw.decode("ascii", errors="replace").strip()
                    _log(f"<- {reply!r} ({elapsed:.2f}s)")
                    if reply != "ERR busy":
                        return reply
                    if attempt == retries:
                        _log(f"still busy after {retries} retries, giving up on this command")
                        return reply
                    _log(f"busy (attempt {attempt + 1}/{retries}), "
                         f"retrying in {BUSY_RETRY_DELAY_S}s")
                    time.sleep(BUSY_RETRY_DELAY_S)
            except _LINK_BROKEN_EXCEPTIONS as exc:
                _log(f"link exception mid-command ({exc!r})")
                if reconnect_attempt == RECONNECT_COMMAND_RETRIES:
                    raise
                self._reconnect()
                _log(f"retrying command {line!r} after reconnect "
                     f"(attempt {reconnect_attempt + 1}/{RECONNECT_COMMAND_RETRIES})")
        raise AssertionError("unreachable")  # satisfies linters

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
        the address the request named as the requester. A normal I2C
        read from such a device just isn't the right operation at all
        (this cost real debugging time: it looked like a NAK/timeout
        bug before the actual protocol behavior was understood). Returns
        the captured response bytes -- see ipmb.parse_response() to
        decode them, and prefer using tests/test_openbic.py's
        send_ipmb_command() helper over calling this directly, since it
        also validates the response actually matches the request (cmd +
        seq) rather than being a stale response to something else.
        """
        hexstr = " ".join(f"{b:02x}" for b in payload)
        cmd = f"I {addr:02x} {our_addr:02x} {hexstr}".strip()
        parts = self._split_ok(self._command(cmd),
                                f"ipmb_request to 0x{addr:02x} failed")
        return bytes(int(x, 16) for x in parts)

    def listen(self, our_addr):
        """Become an I2C slave at our_addr and capture whatever some other
        master writes to us, with no write of our own first. Useful for
        independently testing this path against a master other than the
        bridge itself (this is exactly how we proved the bridge's own
        slave-mode RX path wasn't the problem during development, before
        finding the real bug on OpenBIC's side). Returns the captured
        bytes."""
        parts = self._split_ok(self._command(f"L {our_addr:02x}"),
                                f"listen at 0x{our_addr:02x} failed")
        return bytes(int(x, 16) for x in parts)
