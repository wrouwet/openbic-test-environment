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

# IPMI "App" network function and the universal "Get Device ID" command --
# a reasonable baseline "is it alive at the protocol level" check.
NETFN_APP = 0x06
CMD_GET_DEVICE_ID = 0x01
