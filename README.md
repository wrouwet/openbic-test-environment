# OpenBIC Test Environment

A pytest-based test suite, run from a host PC, for exercising an
[OpenBIC](https://github.com/facebook/OpenBIC) controller over I2C.

This is meant to grow into the full, long-lived OpenBIC test suite over
time, covering every peripheral and interface OpenBIC exposes — not just
the ones a given board port has already implemented. See
["Tests that document unimplemented features"](#tests-that-document-unimplemented-features)
below for how that's tracked.

## What you need before you start

**Hardware:**

1. A **FRDM-MCXA153 board flashed with the bridge firmware** from
   [frdm-mcxa153-usb-i2c-hub](https://github.com/wrouwet/frdm-mcxa153-usb-i2c-hub).
   This board acts as a USB-to-I2C bridge: it exposes a USB CDC virtual
   COM port on its **"MCU USB" port** (a separate USB connector from its
   on-board debug probe) that accepts simple text commands and turns them
   into real I2C transactions. See that repo's README for how to build
   and flash it — you only need to do that once, and the debug USB cable
   does **not** need to stay connected afterward for day-to-day test
   runs, only when reflashing that board's firmware.
2. **An OpenBIC controller wired to that bridge's I2C pins** (SCL/SDA/GND
   on the FRDM board's mikroBUS header — see the firmware repo's README
   for exact pin numbers) and powered on.
3. **One USB cable** from your host PC to the bridge board's "MCU USB"
   port. (The debug USB port is only needed when reflashing the bridge
   firmware itself — not for running this test suite.)

**Software, on the host PC running the tests:**

- Linux (this has been developed and run on Ubuntu/Debian; other
  platforms may work but are untested).
- Python 3.9 or newer, with the `venv` module (`python3 -m venv --help`
  should work; on Debian/Ubuntu this is the `python3-venv` package if
  it's missing).
- Permission to open the serial port the bridge shows up as. On Linux
  this usually means your user needs to be in the `dialout` group:

  ```sh
  sudo usermod -aG dialout $USER
  ```

  **You must fully log out and back in (or reboot) for a new group
  membership to take effect** — a new terminal window alone is often
  *not* enough, since group membership is normally read once at login.
  If you get a `PermissionError`/`could not open port` when running the
  tests below, this is almost always why.

This test suite itself is bridge-agnostic at the protocol level — any
device that speaks the same command protocol over a USB CDC serial port
works — but `bridge.py`'s port auto-detection currently looks
specifically for that firmware's USB VID:PID (`1fc9:0094`).

## Quick start

From a fresh clone of this repo, with the hardware from above already
plugged in and powered on:

```sh
# 1. Create an isolated Python environment and install dependencies into it.
#    (A plain `pip install` into your system Python will likely be refused
#    on modern Debian/Ubuntu -- "externally-managed-environment" -- which
#    is exactly what this venv step avoids.)
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# 2. Run the whole suite.
.venv/bin/pytest tests/
```

That's it — no configuration files to edit, no IP addresses or COM port
numbers to set.

To also save a copy of the full run to `test_report.txt` (everything
that printed to the terminal -- pytest's summary plus every test's wire-
level diagnostics), use `./run_tests.sh` instead of the raw `pytest`
command above; it's the same run, just teed to a file as well. Not
committed to the repo (it's a local run artifact, see `.gitignore`). The bridge's serial port is found automatically by USB
vendor/product ID, not a hardcoded `/dev/ttyACM` number (which one the
kernel assigns it can change across reconnects, especially if another
USB-serial device, like the board's own debug probe, is also plugged in
at the same time).

### Running a subset of tests

```sh
# Just one file (e.g. only the App NetFn tests):
.venv/bin/pytest tests/test_app.py

# Just one test:
.venv/bin/pytest tests/test_app.py::test_get_watchdog_timer

# Everything except the slower stress test:
.venv/bin/pytest tests/ -k "not queue_depth"
```

### Reading the output

The suite runs with `-v -s` by default (see `pytest.ini`), so you'll see
every test name plus its `print()` diagnostics (bytes sent/received on
the wire, timing, retries) rather than pytest's terser default output —
deliberately, since exact wire-level behavior has been what actually
resolved every hard bug found while building this suite. Expect a lot of
output; that's normal and useful, not a sign of trouble.

At the end you'll see a summary line like:

```
======================= 15 passed, 14 xfailed in 18.87s =======================
```

- **`passed`** — real, working behavior confirmed on the hardware. Good.
- **`xfailed`** ("expected failure") — a test for something this
  particular OpenBIC board port doesn't implement yet. This is
  **expected and not a problem** — see the next section. Don't be
  alarmed by these; a healthy run of this suite normally has some.
- **`failed`** — something is actually wrong: either real hardware/
  firmware regressed, or the test environment itself has an issue (wrong
  wiring, board not powered, bridge not plugged in, etc. — see
  Troubleshooting below).
- **`XPASS`** (shown as a failure, not a pass!) — a test marked as
  "not implemented yet" unexpectedly *passed*. This is a **good** signal
  dressed up as a failure on purpose: it means OpenBIC gained support for
  something since this test was written, and the test now needs to be
  edited to assert the real behavior instead of expecting failure. See
  [below](#tests-that-document-unimplemented-features).

A completely clean run (all `passed`, zero `xfailed`) is actually a sign
this suite hasn't been updated to match reality yet, not that OpenBIC
has caught up to every test — as of this writing, several NetFns
(Chassis, most of Sensor/Event, all of SEL) are known-not-yet-implemented
on the board port this has been tested against, and are expected to show
up as `xfailed`.

## Troubleshooting

**`bridge.BridgeError: No FRDM-MCXA153 USB-I2C hub found (looking for USB
VID:PID 1fc9:0094, ...). Is it plugged in?`**
The bridge board isn't enumerating as that USB device. Check: is it
plugged into your host PC via its **"MCU USB"** port (not just the debug
port)? Is it powered on? Run `lsusb` and look for `1fc9:0094` in the
list — if it's not there at all, it's a cabling/power problem, not a
software one. Try a different USB cable — a charge-only cable with no
data lines is a real failure mode that's been hit before on this project
and looks exactly like this.

**A `PermissionError` or "could not open port" when running tests, even
though `lsusb`/`dmesg` shows the device.**
You're very likely missing `dialout` group membership, or added it but
haven't logged out and back in since — see the group membership note
above.

**`bus scan found: []` (empty) on `test_detect_openbic`.**
The bridge itself is working (it answered), but nothing responded on the
I2C bus. Check: is the OpenBIC target board actually powered on? Are
SCL/SDA/GND actually wired between the two boards (and not, e.g.,
swapped)? If this test passed before and now doesn't, also consider
whether the bus might be transiently wedged right after some other
stress — rerunning `tests/test_bus.py` on its own a few seconds later is
a reasonable first check before assuming a wiring problem.

**Tests are slow, or you see `ERR busy` retries in the output.**
This is normal, not a bug: OpenBIC's own response path can take up to a
few seconds internally, and the bridge/test client automatically retries
on a transient "busy" response rather than failing immediately. As long
as the test eventually reports `PASSED`/`XFAILED`, retried-but-succeeded
is a non-issue.

**A test that used to `xfail` now shows as a failure with "XPASS(strict)"
in the output.**
This isn't a bug in the test suite — it means the behavior actually
changed (a gap likely got fixed on the OpenBIC side). See
[Tests that document unimplemented features](#tests-that-document-unimplemented-features).

**Everything was working, then suddenly nothing responds at all.**
If you have more than one USB-serial device plugged in (e.g. the
bridge's own debug probe, which shows up as its own, unrelated serial
port), and things stop working right after an unplug/replug of anything,
this project has hit real, confusing symptoms from `/dev/ttyACM0` and
`/dev/ttyACM1` swapping identities between reconnects in the past. This
suite auto-detects the right port by USB VID:PID specifically to avoid
this, so it shouldn't recur here — but if you're ever debugging by
hand with a raw serial terminal instead of this suite, don't assume a
fixed `/dev/ttyACM` number stays attached to the same physical device
across reconnects.

## Layout

```
bridge.py               Python client for the bridge's text command protocol
conftest.py             pytest fixture that connects the bridge once per session
tests/config.py         shared constants, organized by IPMI NetFn
tests/ipmi_helpers.py   shared request/response round-trip logic + the
                        not_implemented() marker (see below)
tests/test_bus.py       bus presence (everything else assumes this passes)
tests/test_app.py       NetFn App (0x06)
tests/test_chassis.py   NetFn Chassis (0x00)
tests/test_sensor.py    NetFn Sensor/Event (0x04)
tests/test_storage_*.py NetFn Storage (0x0A) — split by sub-area (FRU/SDR/SEL)
tests/test_oem.py       NetFn OEM_1S (0x38)
tests/test_protocol_edge_cases.py
                        framing/checksum and IPMB queue-depth behavior,
                        not tied to any one NetFn
```

One file per NetFn (or NetFn sub-area, where a NetFn covers a lot of
ground — Storage's FRU/SDR/SEL commands are different enough to warrant
separate files). As OpenBIC support grows, add commands to the relevant
existing file rather than growing one file indefinitely; add a new
`test_*.py` for a NetFn or subsystem not covered yet.

## Tests that document unimplemented features

Not every command this suite exercises is actually implemented on every
OpenBIC board port. Rather than skip or omit those, they're written as
real tests and marked with `ipmi_helpers.not_implemented(reason)`:

```python
@not_implemented("Get Chassis Status returns CC_INVALID_CMD (0xC1) -- "
                 "observed live 2026-08-24, not yet implemented on this port.")
def test_get_chassis_status(bridge):
    ...
```

This is `pytest.mark.xfail(strict=True)` under the hood. `strict=True` is
the important part: the moment a board port actually implements the
command and the test starts genuinely passing, xfail flips to **XPASS**
and the run **fails** — a loud, impossible-to-miss signal that a gap just
closed and this test needs to be turned back into a normal one. A
non-strict xfail would just quietly stay green forever and the
improvement would go unnoticed.

**If you see this happen** (a test you expected to `xfail` shows up as a
failing `XPASS` instead): that's good news, not a bug report. Open the
test, remove its `@not_implemented(...)` decorator, and update its body
to assert the real behavior you're now observing instead of the old
expected-failure code.

The `reason` string is the point: say what's actually missing, and how
you know (a completion code observed live, a source reference, a
confirmation from whoever's developing the port). Taken together, every
`not_implemented(...)` reason in the suite *is* this project's live,
always-up-to-date backlog of OpenBIC feature gaps — visible in every test
run's output, not just in a separate doc that can drift out of sync.

## Adding tests

Add a `test_*.py` file under `tests/` (or a test function to an existing
one covering the right NetFn). Test functions that need the bridge take
a `bridge` argument (a `bridge.I2CBridge`, via the session-scoped fixture
in `conftest.py`); most will also want `ipmi_helpers.send_ipmb_command()`
and `ipmi_helpers.assert_completion_code()`. For a command whose behavior
on the target platform isn't confirmed yet, prefer probing it live
against real hardware and writing the test to match what's actually
observed (with a comment saying so) over guessing at IPMI-spec-typical
behavior — this codebase has repeatedly found that guessed completion
codes turn out wrong in ways a live observation wouldn't.
