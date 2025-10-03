"""Main entry point for the I2C sniffer."""

import argparse

from .sniffer import I2CSniffer


def main():
    """Main function."""
    parser = argparse.ArgumentParser(description="I2C bus sniffer")
    parser.add_argument(
        "--logfile", default="i2c_log.txt", help="Log file name (default: i2c_log.txt)"
    )
    args = parser.parse_args()

    sniffer = I2CSniffer(logfile=args.logfile)
    sniffer.run()


if __name__ == "__main__":
    main()
