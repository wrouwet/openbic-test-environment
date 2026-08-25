# OpenBIC Test Environment

A pytest-based test suite, run from a host PC, for exercising an
[OpenBIC](https://github.com/facebook/OpenBIC) controller over I2C.

This is meant to grow into the full, long-lived OpenBIC test suite over
time, covering every peripheral and interface OpenBIC exposes — not just
the ones a given board port has already implemented. See "Testing
unimplemented features" below for how that's tracked.

## Prerequisite: a USB-to-I2C bridge

This project assumes a **USB-to-I2C bridge** is connected between this
host PC and the OpenBIC controller's I2C bus — specifically the one
built in
[frdm-mcxa153-usb-i2c-hub](https://github.com/wrouwet/frdm-mcxa153-usb-i2c-hub):
a FRDM-MCXA153 board flashed with bridge firmware that exposes a USB CDC
virtual COM port accepting simple text commands (`S`/`W`/`R`/`X`) and
translating them into I2C transactions on its own LPI2C0 master. See
that repo for flashing the board and wiring the OpenBIC target to it.

This test suite itself is bridge-agnostic at the protocol level — any
device that speaks the same command protocol over a USB CDC serial port
works — but `bridge.py`'s port auto-detection currently looks
specifically for that firmware's USB VID:PID (`1fc9:0094`).

## Setup

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## Running

With the bridge plugged in (over its own "MCU USB" port) and the
OpenBIC target wired to it:

```sh
.venv/bin/pytest tests/
```

The bridge's serial port is auto-detected by USB VID:PID, not a
hardcoded `/dev/ttyACM` number — which one the kernel assigns it can
change across reconnects, especially if other CDC devices (like a debug
probe) are also plugged in.

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

## Testing unimplemented features

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
