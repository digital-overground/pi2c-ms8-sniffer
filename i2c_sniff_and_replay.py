#!/usr/bin/env python3
"""
i2c_sniff_and_replay.py

- Sniffs I2C traffic (SDA=SCL GPIO pins default to Pi hardware pins 2 & 3)
  using pigpio in a polling loop (works reliably on Raspberry Pi).
- Allows issuing hard-coded "macros" (timed sequences of I2C writes)
  while pausing sniffing to avoid collisions.

Run with sudo:
  sudo python3 i2c_sniff_and_replay.py --log logfile.txt

While running, press:
  u  Enter  -> send "vol_up" macro
  d  Enter  -> send "vol_down" macro
  q  Enter  -> quit

You MUST have pigpio daemon running:
  sudo systemctl start pigpiod
"""

import argparse
import errno
import os
import sys
import threading
import time
from datetime import datetime

import pigpio
from smbus2 import SMBus, i2c_msg

# Default GPIO pins (BCM)
SDA_PIN = 2  # GPIO2 (pin 3)
SCL_PIN = 3  # GPIO3 (pin 5)

I2C_BUS = 1  # /dev/i2c-1

# Hard-coded macros (address, data list, delay_after_ms)
# These are examples derived from your captures. Adjust if needed.
VOL_UP_MACRO = [
    (0x03, [0x02, 0x21], 40),  # prep
    (0x05, [0x2A, 0xC8, 0xA0], 80),  # action
    (0x20, [0x45, 0x99, 0x28, 0x2C, 0xD8, 0x48, 0xF0, 0x98, 0x50, 0x98], 0),
]

VOL_DOWN_MACRO = [
    (0x03, [0x02, 0x09, 0x07, 0x22], 40),
    (0x02, [0x2C, 0xCA], 80),
    # optionally add other writes if needed
]

# Sniffer settings
DEFAULT_DURATION = None  # None = run until user quits
DEFAULT_LOGFILE = "i2c_sniffer.log"


# ======================================================================
# Utilities
# ======================================================================
def timestamp():
    return datetime.now().strftime("%H:%M:%S.%f")[:-3]


# ======================================================================
# I2C Sniffer using pigpio (polling-style loops, but interruptible)
# ======================================================================
class I2CSniffer(threading.Thread):
    def __init__(
        self,
        pi,
        sda=SDA_PIN,
        scl=SCL_PIN,
        logfile=DEFAULT_LOGFILE,
        duration=None,
        pause_event=None,
    ):
        super().__init__(daemon=True)
        self.pi = pi
        self.sda = sda
        self.scl = scl
        self.logfile_name = logfile
        self.duration = duration
        self._stop_event = threading.Event()
        self.pause_event = (
            pause_event or threading.Event()
        )  # when set -> pause sniffing
        # open logfile
        self.logfile = open(self.logfile_name, "a", buffering=1)
        # verify pins
        self.pi.set_mode(self.sda, pigpio.INPUT)
        self.pi.set_mode(self.scl, pigpio.INPUT)

    def log(self, msg):
        line = f"[{timestamp()}] {msg}"
        print(line)
        self.logfile.write(line + "\n")

    def wait_for_edge(self, pin, level, timeout_s=0.1):
        """
        Wait for pin to reach level, but return earlier if paused/stopped.
        tight loop with tiny sleep so we can be responsive to pause_event.
        """
        deadline = time.time() + timeout_s
        # loops until level observed OR paused OR stopped OR timeout
        while True:
            if self._stop_event.is_set():
                raise RuntimeError("Sniffer stopped")
            if self.pause_event.is_set():
                # while paused, yield CPU and wait for resume
                time.sleep(0.001)
                deadline = time.time() + timeout_s
                continue
            if time.time() > deadline:
                return False
            if self.pi.read(pin) == level:
                return True
            # tiny sleep to avoid pegging CPU
            time.sleep(0.0002)

    def read_bit(self):
        """Read single I2C bit: sample SDA while SCL=1 (clock high)."""
        # Wait for rising edge of SCL
        if not self.wait_for_edge(self.scl, 1, timeout_s=0.1):
            raise TimeoutError("SCL rising edge timeout")
        bit = self.pi.read(self.sda)
        # Wait for falling edge of SCL
        if not self.wait_for_edge(self.scl, 0, timeout_s=0.1):
            raise TimeoutError("SCL falling edge timeout")
        return bit

    def read_byte(self):
        val = 0
        for _ in range(8):
            b = self.read_bit()
            val = (val << 1) | (b & 1)
        # ACK bit (master releases SDA, then slave drives ack during 9th clock)
        ack = self.read_bit()
        return val, ack

    def run(self):
        self.log(
            f"Sniffer started (SDA={self.sda}, SCL={self.scl}). Logging to {self.logfile_name}"
        )
        start_t = time.time()
        try:
            while True:
                # duration check
                if self.duration and (time.time() - start_t) >= self.duration:
                    self.log("Sniffer duration elapsed, stopping.")
                    break
                if self._stop_event.is_set():
                    break
                # if paused, yield
                if self.pause_event.is_set():
                    time.sleep(0.01)
                    continue

                # Wait for START condition: SDA goes low while SCL is high.
                # We'll poll for SCL high + SDA low
                if not (self.pi.read(self.scl) == 1 and self.pi.read(self.sda) == 0):
                    time.sleep(0.0005)
                    continue

                self.log("START detected")

                # Read addr+R/W
                try:
                    addr_rw, ack = self.read_byte()
                except TimeoutError as ex:
                    self.log(f"Byte read timeout after START: {ex}")
                    continue

                addr = addr_rw >> 1
                rw = addr_rw & 1
                rw_str = "READ" if rw else "WRITE"
                self.log(
                    f"Master initiated transaction: Address=0x{addr:02X}, {rw_str}, ACK={ack == 0}"
                )

                # Read payload bytes until STOP
                while True:
                    # stop condition: SCL=1 and SDA=1
                    if self.pause_event.is_set():
                        break
                    if self.pi.read(self.scl) == 1 and self.pi.read(self.sda) == 1:
                        self.log("STOP detected\n")
                        break
                    try:
                        byte, ack = self.read_byte()
                    except TimeoutError as ex:
                        self.log(f"Byte read timeout within transaction: {ex}")
                        break
                    self.log(f"  Data: 0x{byte:02X}, ACK={ack == 0}")
        except Exception as e:
            self.log(f"Sniffer exception: {e}")
        finally:
            self.log("Sniffer cleaning up.")
            try:
                self.logfile.close()
            except Exception:
                pass

    def stop(self):
        self._stop_event.set()


# ======================================================================
# Macro replay function (pause sniffer, perform writes, resume)
# ======================================================================
def send_macro(macro, bus_num=I2C_BUS, pause_event=None):
    """
    macro: list of tuples (addr, [bytes], delay_after_ms)
    pause_event: threading.Event used to pause sniffing
    """
    if pause_event is None:
        raise RuntimeError("pause_event required")

    # Request sniffer pause
    pause_event.set()
    time.sleep(0.02)  # small settling time

    print(f"[{timestamp()}] Sending macro with {len(macro)} writes...")

    # Open bus
    try:
        bus = SMBus(bus_num)
    except Exception as e:
        print(f"[{timestamp()}] Failed to open i2c bus {bus_num}: {e}")
        pause_event.clear()
        return

    try:
        for idx, (addr, data, delay_ms) in enumerate(macro, start=1):
            try:
                # build write message and send
                msg = i2c_msg.write(addr, bytes(data))
                bus.i2c_rdwr(msg)
                print(
                    f"[{timestamp()}] Sent to 0x{addr:02X}: {' '.join(f'{b:02X}' for b in data)}"
                )
            except OSError as oe:
                # Provide detailed errno and strerror
                err_no = oe.errno if hasattr(oe, "errno") else None
                err_str = os.strerror(err_no) if err_no else str(oe)
                print(
                    f"[{timestamp()}] OSError while writing to 0x{addr:02X}: errno={err_no} ({err_str})"
                )
                # For debugging, also print full exception
                print(f"  exception: {oe!r}")
            except Exception as exc:
                print(
                    f"[{timestamp()}] Exception while writing to 0x{addr:02X}: {exc!r}"
                )

            # delay after write (simulate screen timing)
            if delay_ms:
                time.sleep(delay_ms / 1000.0)

    finally:
        try:
            bus.close()
        except Exception:
            pass
        # Clear pause -> resume sniffing
        time.sleep(0.02)
        pause_event.clear()
        print(f"[{timestamp()}] Macro send complete; sniffer resumed.")


# ======================================================================
# Small interactive runner
# ======================================================================
def main():
    parser = argparse.ArgumentParser(description="I2C sniff + replay tool")
    parser.add_argument("--sda", type=int, default=SDA_PIN, help="SDA GPIO (BCM)")
    parser.add_argument("--scl", type=int, default=SCL_PIN, help="SCL GPIO (BCM)")
    parser.add_argument("--log", default=DEFAULT_LOGFILE, help="Log filename")
    parser.add_argument(
        "--duration", type=int, default=0, help="Sniff duration seconds (0=until quit)"
    )
    args = parser.parse_args()

    # ensure pigpio running
    pi = pigpio.pi()
    if not pi.connected:
        print("pigpio not running. Start with: sudo systemctl start pigpiod")
        sys.exit(1)

    pause_event = threading.Event()
    duration = args.duration if args.duration > 0 else None

    sniffer = I2CSniffer(
        pi,
        sda=args.sda,
        scl=args.scl,
        logfile=args.log,
        duration=duration,
        pause_event=pause_event,
    )
    sniffer.start()

    print("\nInteractive control:")
    print("  'u' + Enter  => send vol_up macro")
    print("  'd' + Enter  => send vol_down macro")
    print("  'q' + Enter  => quit\n")

    try:
        while True:
            cmd = input().strip().lower()
            if cmd == "u":
                send_macro(VOL_UP_MACRO, bus_num=I2C_BUS, pause_event=pause_event)
            elif cmd == "d":
                send_macro(VOL_DOWN_MACRO, bus_num=I2C_BUS, pause_event=pause_event)
            elif cmd == "q":
                print("Quitting...")
                break
            else:
                print("Unknown. Use 'u', 'd', or 'q'.")
    except KeyboardInterrupt:
        print("Interrupted by user.")
    finally:
        sniffer.stop()
        sniffer.join(timeout=2.0)
        try:
            pi.stop()
        except Exception:
            pass
        print("Done.")


if __name__ == "__main__":
    main()
