"""Shared constants for the OpenBIC test suite."""

# 7-bit I2C address of the OpenBIC controller on the far side of the bridge.
# Confirmed live (2026-08-24) against meta-facebook/mcx-n9xx-evk
# (full-board-port branch): BIC_IPMB_ADDRESS in plat_ipmb.h is 0x20, and a
# malformed write to this address produced a matching "Invalid IPMB message
# checksum" log on the OpenBIC console.
OPENBIC_ADDR = 0x20

# Our bridge's I2C address when acting as the IPMB requester (arbitrary,
# just needs to not collide with a real device on the bus).
OUR_IPMB_ADDR = 0x08

# IPMI "App" network function and its universal, read-only commands --
# safe to run against any compliant BMC/BIC since none of them change
# state (deliberately avoiding Cold/Warm Reset, Set ACPI Power State,
# etc. against live hardware under active development).
NETFN_APP = 0x06
CMD_GET_DEVICE_ID = 0x01
CMD_GET_SELF_TEST_RESULTS = 0x04
CMD_GET_DEVICE_GUID = 0x08

# Get Self Test Results, byte 1 (of 2): the two "everything's fine" values
# per the IPMI spec -- 0x55 (no error) or 0x56 (self-test not implemented).
SELF_TEST_OK_CODES = (0x55, 0x56)

# 0x57 ("corrupted or inaccessible data or devices") + detail byte 0x36 is
# ALSO an accepted outcome on this specific board/port, not a failure --
# confirmed against source with the peer session developing this OpenBIC
# port (meta-facebook/mcx-n9xx-evk, full-board-port branch), 2026-08-24.
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

# IPMI "Sensor/Event" network function. Get Sensor Reading (0x2D) is the
# one command we exercise here.
NETFN_SENSOR_EVENT = 0x04
CMD_GET_SENSOR_READING = 0x2D

# Confirmed against source (SENSOR_GET_SENSOR_READING() in
# sensor_handler.c), 2026-08-24: on this board, sensor_init() bails out
# early ("Init sensor size is zero") on a code path that never sets
# enable_sensor_poll_thread = false (that only happens on a *different*
# early-exit, a size *mismatch*) and never allocates sensor_config.
# get_sensor_reading() then hits its CHECK_NULL_ARG_WITH_RETURN(cfg_table,
# ...) guard and safely returns this, for *any* sensor number byte -- not
# 0xCB "requested sensor/record not present" as you might otherwise
# expect for an unconfigured sensor. If this board ever gets a real
# sensor table, this should change to something more specific and this
# constant should be revisited.
CC_UNSPECIFIED_ERROR = 0xFF

# IPMI "Storage" network function, and the two FRU-related commands we
# exercise here. Confirmed against source (plat_fru.c / fru.c), 2026-08-24.
NETFN_STORAGE = 0x0A
CMD_GET_FRU_INVENTORY_AREA_INFO = 0x10
CMD_READ_FRU_DATA = 0x11

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

# IPMI OEM network function used by this platform (NETFN_OEM_1S_REQ in
# the OpenBIC source).
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
# decode as a *nonzero* IANA enterprise number (real Meta OEM-1S commands
# are IANA-prefixed by convention; the dispatcher doesn't care *which*
# IANA, just that one's present). Any other case (not MSG_IN/MSG_OUT,
# and not properly IANA-prefixed -- e.g. no data at all) falls through to
# a *different*, earlier rejection: CC_INVALID_IANA (0x84). So there are
# three distinct, real OEM_1S outcomes depending on exactly what's sent,
# not just one "unimplemented command" case -- worth testing as separate,
# named behaviors rather than picking one cmd value and expecting it to
# represent "OEM commands in general".
CC_INVALID_IANA = 0x84
CC_INVALID_CMD = 0xC1

# A nonzero 3-byte IANA enterprise number, little-endian per the
# dispatcher's decode -- this happens to be Meta's own (0x00A015), but
# per the peer's confirmation the dispatcher accepts literally any
# nonzero value here, it doesn't validate which IANA it is.
OEM_IANA_BYTES = bytes([0x15, 0xA0, 0x00])
