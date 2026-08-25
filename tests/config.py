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
