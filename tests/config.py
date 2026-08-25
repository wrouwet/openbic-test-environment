"""Shared constants for the OpenBIC test suite.

Organized by IPMI NetFn, since that's how the test files themselves are
split (test_app.py, test_chassis.py, ...). Platform-specific facts here
(what's implemented, what completion code a gap actually returns) are
either confirmed against source with the peer session developing this
OpenBIC port (meta-facebook/mcx-n9xx-evk, full-board-port branch), or
directly observed live against the real board -- never guessed. See each
constant's comment for which, and the date.

Peer-confirmed platform inventory (2026-08-24), for context on why so
much of this board reports "not implemented" rather than real values:
this EVK has almost nothing physically populated beyond bring-up
essentials -- sensor and SDR tables are genuinely empty (not
partially-configured), there is no fan/PWM hardware at all, exactly one
GPIO is monitored (a debounce-only button, not exposed over IPMI), there
are no VRs or other polled I2C ICs, and there's a single FRU pointed at
an EEPROM address with nothing wired to it. What IS real, working
infrastructure on this platform: the watchdog, NVS persistent storage,
HWINFO device ID, the dual-core mailbox, the IPMB transport, and the
core IPMI NetFn dispatch pipeline itself (App/Chassis/Sensor/Storage/OEM
routing all genuinely exist -- individual commands within them are what's
often missing). Firmware update (PLDM/MCTP or OEM-based) doesn't exist
on this platform at all yet -- a real, currently-unclaimed gap, not
something this suite can test until one exists.
"""

CC_SUCCESS = 0x00

# 7-bit I2C address of the OpenBIC controller on the far side of the bridge.
# Confirmed live (2026-08-24) against meta-facebook/mcx-n9xx-evk
# (full-board-port branch): BIC_IPMB_ADDRESS in plat_ipmb.h is 0x20, and a
# malformed write to this address produced a matching "Invalid IPMB message
# checksum" log on the OpenBIC console.
OPENBIC_ADDR = 0x20

# Our bridge's I2C address when acting as the IPMB requester (arbitrary,
# just needs to not collide with a real device on the bus).
OUR_IPMB_ADDR = 0x08


# ---------------------------------------------------------------------------
# NetFn App (0x06) -- universal, read-only commands only (deliberately
# avoiding Cold/Warm Reset, Set ACPI Power State, Set Watchdog Timer, etc.
# against live hardware under active development).
# ---------------------------------------------------------------------------
NETFN_APP = 0x06
CMD_GET_DEVICE_ID = 0x01
CMD_GET_SELF_TEST_RESULTS = 0x04
CMD_GET_DEVICE_GUID = 0x08
CMD_GET_ACPI_POWER_STATE = 0x07
CMD_GET_WATCHDOG_TIMER = 0x25
CMD_GET_BMC_GLOBAL_ENABLES = 0x2F
CMD_GET_SYSTEM_GUID = 0x37
CMD_GET_CHANNEL_INFO = 0x42

# Sentinel channel number meaning "the channel this request arrived on"
# (0x0E), used with Get Channel Info so we don't need to know or guess
# this platform's real IPMB channel number.
CHANNEL_THIS_CHANNEL = 0x0E

# Get Self Test Results, byte 1 (of 2): the two "everything's fine" values
# per the IPMI spec -- 0x55 (no error) or 0x56 (self-test not implemented).
SELF_TEST_OK_CODES = (0x55, 0x56)

# 0x57 ("corrupted or inaccessible data or devices") + detail byte 0x36 is
# ALSO an accepted outcome on this specific board/port, not a failure --
# confirmed against source with the peer session, 2026-08-24.
# APP_GET_SELFTEST_RESULTS() in common/service/ipmi/app_handler.c does two
# genuinely-expected-to-fail things on this hardware: FRU_read() against
# the FRU EEPROM's I2C address, which has nothing physically wired there
# per this board's README (sets bits 2 cannotAccessBmcFruDev + 5
# internalCorrupt), and a check of is_sdr_not_init, true because no SDR
# table is populated for this port (sets bits 1 cannotAccessSdrRepo + 4
# sdrRepoEmpty). bits 1,2,4,5 -> 0b00110110 = 0x36 exactly. If this
# platform ever gets a real FRU EEPROM and populated SDR table, this
# detail byte should change and this exception should be revisited.
SELF_TEST_EXPECTED_ERROR = (0x57, 0x36)

# CC_UNSPECIFIED_ERROR (0xFF): confirmed against source (SENSOR_GET_SENSOR_
# READING() in sensor_handler.c), 2026-08-24, as the code Get Sensor
# Reading returns on this board (see netfn_sensor comment below) -- kept
# here rather than duplicated per-file since App's Get System GUID was
# also observed live to return this same code (see CMD_GET_SYSTEM_GUID's
# test for the open question about why).
CC_UNSPECIFIED_ERROR = 0xFF

# CC_INVALID_CMD (0xC1): the generic IPMI "Invalid Command" completion
# code. Confirmed against source, 2026-08-24, as what IPMI_OEM_1S_handler()
# in plat_stubs.c unconditionally returns (see netfn_oem comment below);
# also the code observed live for essentially every genuinely-unimplemented
# App/Chassis/Sensor/Storage command probed on this platform (Get Chassis
# Status, Get System Restart Cause, Get POH Counter, Get ACPI Power State,
# Get BMC Global Enables, Get Channel Info, Get SDR Repository Info, Get
# SEL Info, Reserve SEL, Get SEL Time, Get Sensor Type, Get Sensor
# Threshold, Get Sensor Event Enable, Get Sensor Event Status -- all
# observed live 2026-08-24). This is the platform's normal, working
# "recognized NetFn, but this particular command isn't implemented" signal
# -- distinguish it from CC_UNSPECIFIED_ERROR above, which so far has only
# shown up on commands that DO reach a real (if guarded/stubbed) handler.
CC_INVALID_CMD = 0xC1


# ---------------------------------------------------------------------------
# NetFn Chassis (0x00) -- read-only only. Chassis Control / Chassis Reset
# are deliberately never exercised here (state-changing: would power-cycle
# or reset real hardware).
# ---------------------------------------------------------------------------
NETFN_CHASSIS = 0x00
CMD_GET_CHASSIS_STATUS = 0x01
CMD_GET_SYSTEM_RESTART_CAUSE = 0x07
CMD_GET_POH_COUNTER = 0x0F


# ---------------------------------------------------------------------------
# NetFn Sensor/Event (0x04).
# ---------------------------------------------------------------------------
NETFN_SENSOR_EVENT = 0x04
CMD_GET_SENSOR_READING = 0x2D
CMD_GET_SENSOR_TYPE = 0x2F
CMD_GET_SENSOR_THRESHOLD = 0x27
CMD_GET_SENSOR_EVENT_ENABLE = 0x29
CMD_GET_SENSOR_EVENT_STATUS = 0x2B

# Arbitrary sensor number -- see CC_UNSPECIFIED_ERROR's comment above and
# CC_INVALID_CMD's: which one a given sensor command returns doesn't
# depend on which sensor number is asked about (there are none configured
# either way), so any value works, and this one is reused across all of
# them for consistency.
SENSOR_NUMBER = 0x01

# Confirmed against source (SENSOR_GET_SENSOR_READING() in
# sensor_handler.c), 2026-08-24: on this board, sensor_init() bails out
# early ("Init sensor size is zero") on a code path that never sets
# enable_sensor_poll_thread = false (that only happens on a *different*
# early-exit, a size *mismatch*) and never allocates sensor_config.
# get_sensor_reading() then hits its CHECK_NULL_ARG_WITH_RETURN(cfg_table,
# ...) guard and safely returns CC_UNSPECIFIED_ERROR, for *any* sensor
# number byte -- not 0xCB "requested sensor/record not present" as you
# might otherwise expect for an unconfigured sensor, and notably NOT
# CC_INVALID_CMD either: Get Sensor Reading really is dispatched to a
# real handler, unlike its siblings (Get Sensor Type/Threshold/Event
# Enable/Event Status), which were observed live (2026-08-24) to return
# a flat CC_INVALID_CMD instead -- i.e. those aren't wired into the
# dispatch table at all yet, while Get Sensor Reading is wired in but
# guards safely on the empty config. If this board ever gets a real
# sensor table, all of these should change and be revisited.


# ---------------------------------------------------------------------------
# NetFn Storage (0x0A).
# ---------------------------------------------------------------------------
NETFN_STORAGE = 0x0A
CMD_GET_FRU_INVENTORY_AREA_INFO = 0x10
CMD_READ_FRU_DATA = 0x11
CMD_GET_SDR_REPOSITORY_INFO = 0x20
CMD_RESERVE_SDR_REPOSITORY = 0x22
CMD_GET_SEL_INFO = 0x40
CMD_RESERVE_SEL = 0x42
CMD_GET_SEL_TIME = 0x48

# MCX_N9XX_EVK_FRU_ID from plat_fru.c -- the only valid FRU ID on this
# platform (MAX_FRU_ID == 1).
FRU_ID = 0x00

# Get FRU Inventory Area Info is a static config lookup (find_FRU_size()
# in fru.c never touches the I2C bus), so it succeeds even though nothing
# is physically wired to the FRU EEPROM address -- expect CC_SUCCESS.
#
# Read FRU Data, in contrast, genuinely calls FRU_read() against that
# same (unwired) I2C address -- same underlying I2C failure as the
# self-test finding above, but mapped to a specific completion code here
# instead of a raw status byte: CC_FRU_DEV_BUSY (0x81).
CC_FRU_DEV_BUSY = 0x81

# Observed live, 2026-08-24: Reserve SDR Repository genuinely works
# (CC_SUCCESS, hands back a real reservation ID) even though Get SDR
# Repository Info -- and every SEL command, including its own Reserve
# SEL sibling -- returns CC_INVALID_CMD. Reservation issuing appears to
# be shared generic infrastructure (also used by FRU/SEL reservation
# flows) that's wired in regardless of whether the specific repository
# it's reserving space in has any real data behind it yet; a genuine,
# real asymmetry rather than a fluke -- worth keeping as two separate
# tests (test_storage_sdr.py) rather than assuming they'd behave the
# same way.


# ---------------------------------------------------------------------------
# NetFn OEM_1S (0x38) -- Meta's OEM network function on this platform.
# ---------------------------------------------------------------------------
NETFN_OEM_1S = 0x38

# An arbitrary command byte for exercising OEM_1S paths below -- MUST NOT
# be 0x01 (CMD_OEM_1S_MSG_IN) or 0x02 (CMD_OEM_1S_MSG_OUT): the shared
# ipmi_cmd_handle()/pal_is_not_return_cmd() path in ipmi.c special-cases
# exactly those two as fire-and-forget, real Meta OEM-1S async
# message-passing semantics with NO response ever sent, by design --
# confirmed against source with the peer session after 0x01 initially
# looked like a bug (a full 4s bridge listen() timeout, no response at
# all).
CMD_OEM_ARBITRARY = 0x03

# Full picture confirmed against source with the peer session, 2026-08-24
# (took two rounds -- the first answer only checked the stub's own
# unconditional body and missed that it's gated before ever being
# called): ipmi_cmd_handle()'s NETFN_OEM_1S_REQ case only dispatches to
# IPMI_OEM_1S_handler() -- the actual stub, which unconditionally returns
# CC_INVALID_CMD (0xC1) -- when data_len >= 3 AND the first 3 data bytes
# decode as a nonzero IANA enterprise number (real Meta OEM-1S commands
# are IANA-prefixed by convention; the dispatcher doesn't care *which*
# IANA, just that one's present). Any other case (not MSG_IN/MSG_OUT,
# and not properly IANA-prefixed -- e.g. no data at all) falls through to
# a *different*, earlier rejection: CC_INVALID_IANA (0x84). Also
# confirmed, 2026-08-24: zero OEM_1S subcommands are actually implemented
# on this platform -- the stub is a single unconditional 3-line function
# with no dispatch/switch inside it at all, so CC_INVALID_CMD is the only
# outcome the real stub can ever produce right now, for any command byte.
CC_INVALID_IANA = 0x84

# A nonzero 3-byte IANA enterprise number, little-endian per the
# dispatcher's decode -- this happens to be Meta's own (0x00A015), but
# per the peer's confirmation the dispatcher accepts literally any
# nonzero value here, it doesn't validate which IANA it is.
OEM_IANA_BYTES = bytes([0x15, 0xA0, 0x00])
