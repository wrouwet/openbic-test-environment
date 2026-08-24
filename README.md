# OpenBIC Test Environment

A pytest-based test suite, run from a host PC, for exercising an
[OpenBIC](https://github.com/facebook/OpenBIC) controller over I2C.

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
bridge.py         Python client for the bridge's text command protocol
conftest.py       pytest fixture that connects the bridge once per session
tests/config.py   shared constants (e.g. OPENBIC_ADDR)
tests/test_*.py   the actual test cases
```

## Adding tests

Add a `test_*.py` file under `tests/`; test functions that need the
bridge take a `bridge` argument (a `bridge.I2CBridge`, via the
session-scoped fixture in `conftest.py`). See `tests/test_openbic.py`
for the pattern.
