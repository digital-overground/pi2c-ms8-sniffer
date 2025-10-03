"""I2C bus sniffer implementation."""

import argparse
from datetime import datetime

import pigpio

# GPIO pin assignments
SDA = 2  # GPIO 2 (pin 3)
SCL = 3  # GPIO 3 (pin 5)

# Log file settings
LOG_FILENAME = "i2c_log.txt"


class I2CSniffer:
    """I2C bus sniffer using pigpio library."""

    def __init__(self, sda_pin=SDA, scl_pin=SCL, logfile=LOG_FILENAME):
        self.sda = sda_pin
        self.scl = scl_pin
        self.logfile_name = logfile
        self._check_logfile()
        self.logfile = open(logfile, "w", buffering=1)
        self.pi = pigpio.pi()

        if not self.pi.connected:
            raise RuntimeError("Failed to connect to pigpio daemon")

    def _check_logfile(self):
        """Check if logfile exists and prompt for overwrite."""
        import os

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
        """Wait for specific edge on GPIO pin."""
        while self.pi.read(pin) != edge:
            pass

    def read_bit(self):
        """Read single bit from I2C bus."""
        self.wait_for_edge(self.scl, 1)
        bit = self.pi.read(self.sda)
        self.wait_for_edge(self.scl, 0)
        return bit

    def read_byte(self):
        """Read byte from I2C bus with ACK status."""
        val = 0
        for i in range(8):
            val = (val << 1) | self.read_bit()
        ack = self.read_bit()
        return val, ack

    def run(self):
        """Main sniffer loop."""
        self.log("Logging started")

        try:
            while True:
                while self.pi.read(self.sda) == 1 or self.pi.read(self.scl) == 0:
                    pass

                self.log("START detected")
                addr_rw, ack = self.read_byte()
                addr = addr_rw >> 1
                rw = addr_rw & 1
                rw_str = "READ" if rw else "WRITE"
                self.log(f"Address: 0x{addr:02X} {rw_str}, ACK={ack == 0}")

                while True:
                    if self.pi.read(self.scl) == 1 and self.pi.read(self.sda) == 1:
                        self.log("STOP detected\n")
                        break
                    byte, ack = self.read_byte()
                    self.log(f"  Data: 0x{byte:02X}, ACK={ack == 0}")

        except KeyboardInterrupt:
            self.log("Stopped by user.")
            self.cleanup()
            print("\nLogging complete.")

    def cleanup(self):
        """Clean up resources."""
        self.logfile.close()
        self.pi.stop()


def main():
    """Main function."""
    parser = argparse.ArgumentParser(description="I2C bus sniffer")
    parser.add_argument(
        "--logfile",
        default="i2c_log.txt",
        help="Log file name (default: i2c_log.txt)",
    )
    args = parser.parse_args()

    sniffer = I2CSniffer(logfile=args.logfile)
    sniffer.run()


if __name__ == "__main__":
    main()
