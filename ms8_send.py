#!/usr/bin/env python3
import argparse
import time

import smbus2

# I2C bus (Raspberry Pi uses bus 1)
I2C_BUS = 1

# Commands discovered from sniff logs
COMMANDS = {
    "up": [
        {"addr": 0x03, "data": [0x02, 0x21]},
        {"addr": 0x05, "data": [0x2A, 0xC8, 0xA0]},
    ],
    "down": [
        {"addr": 0x03, "data": [0x02, 0x09, 0x07, 0x22]},
        {"addr": 0x02, "data": [0x2C, 0xCA]},
    ],
}


def send_command(bus, addr, data):
    """Send a raw I2C write."""
    try:
        bus.write_i2c_block_data(addr, data[0], data[1:])
        print(f"Sent to 0x{addr:02X}: {data}")
    except Exception as e:
        print(f"Error sending to 0x{addr:02X}: {e}")


def main():
    parser = argparse.ArgumentParser(
        description="Send test commands to JBL MS-8 via I2C"
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--up", action="store_true", help="Send Volume Up command")
    group.add_argument("--down", action="store_true", help="Send Volume Down command")
    args = parser.parse_args()

    action = "up" if args.up else "down"

    print(f"Sending '{action.upper()}' command sequence...")
    bus = smbus2.SMBus(I2C_BUS)

    for cmd in COMMANDS[action]:
        send_command(bus, cmd["addr"], cmd["data"])
        time.sleep(0.1)  # short delay between writes

    bus.close()
    print("Done.")


if __name__ == "__main__":
    main()
