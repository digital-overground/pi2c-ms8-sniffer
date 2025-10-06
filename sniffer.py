#!/usr/bin/env python3
"""
I2C bus sniffer with master/slave direction tracking.
Logs 20 seconds of bus activity to console and file.
"""

import argparse
import os
import time
from datetime import datetime

import pigpio

SDA = 2  # GPIO 2 (pin 3)
SCL = 3  # GPIO 3 (pin 5)
LOG_FILENAME = "i2c_log.txt"


class I2CSniffer:
    def __init__(self, sda_pin=SDA, scl_pin=SCL, logfile=LOG_FILENAME, duration=20):
        self.sda = sda_pin
        self.scl = scl_pin
        self.logfile_name = logfile
        self.duration = duration
        self._check_logfile()
        self.logfile = open(logfile, "w", buffering=1)
        self.pi = pigpio.pi()

        if not self.pi.connected:
            raise RuntimeError("Failed to connect to pigpio daemon")

    def _check_logfile(self):
        """Check if logfile exists and prompt for overwrite."""
        if os.path.exists(self.logfile_name):
            response = input(
                f"Log file '{self.logfile_name}' exists. Overwrite? (y/N): "
            )
            if response.lower() != "y":
                raise FileExistsError("Log file exists and overwrite not confirmed")

    def log(self, msg):
        """Log message with timestamp."""
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        print(f"[{timestamp}] {msg}")
        self.logfile.write(f"[{timestamp}] {msg}\n")

    def wait_for_edge(self, pin, edge):
        while self.pi.read(pin) != edge:
            pass

    def read_bit(self):
        self.wait_for_edge(self.scl, 1)
        bit = self.pi.read(self.sda)
        self.wait_for_edge(self.scl, 0)
        return bit

    def read_byte(self):
        val = 0
        for _ in range(8):
            val = (val << 1) | self.read_bit()
        ack = self.read_bit()
        return val, ack

    def run(self):
        self.log(f"Logging started for {self.duration} seconds")
        start_time = time.time()

        try:
            while time.time() - start_time < self.duration:
                # Wait for START condition: SDA falls while SCL high
                while not (self.pi.read(self.scl) == 1 and self.pi.read(self.sda) == 0):
                    if time.time() - start_time >= self.duration:
                        raise TimeoutError
                    pass

                self.log("START detected")

                # Read address and R/W bit
                addr_rw, ack = self.read_byte()
                addr = addr_rw >> 1
                rw = addr_rw & 1
                rw_str = "READ" if rw else "WRITE"

                self.log(
                    f"Master initiated transaction: Address=0x{addr:02X}, {rw_str}, ACK={ack == 0}"
                )

                # Read subsequent bytes until STOP condition
                while True:
                    if self.pi.read(self.scl) == 1 and self.pi.read(self.sda) == 1:
                        self.log("STOP detected\n")
                        break
                    byte, ack = self.read_byte()
                    self.log(f"  Data: 0x{byte:02X}, ACK={ack == 0}")

        except TimeoutError:
            self.log("Reached 20 second capture limit.")
        except KeyboardInterrupt:
            self.log("Stopped by user.")
        finally:
            self.cleanup()
            print("\nLogging complete.")

    def cleanup(self):
        self.logfile.close()
        self.pi.stop()


def main():
    parser = argparse.ArgumentParser(
        description="I2C bus sniffer with master direction tracking"
    )
    parser.add_argument(
        "--logfile",
        default="i2c_log.txt",
        help="Log file name (default: i2c_log.txt)",
    )
    parser.add_argument(
        "--duration",
        type=int,
        default=20,
        help="Capture duration in seconds (default: 20)",
    )
    args = parser.parse_args()

    sniffer = I2CSniffer(logfile=args.logfile, duration=args.duration)
    sniffer.run()


if __name__ == "__main__":
    main()
