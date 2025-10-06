#!/usr/bin/env python3
"""
I2C bus sniffer with master/slave direction tracking + delta replay.

Workflow:
  1) Sniff baseline for 10s (do nothing) -> baseline_log
  2) Press Enter -> sniff 10s while you press target control(s) -> command_log
  3) Compute multiset-difference (transactions that appear more often in command_log)
  4) Show WRITE candidates + preserved inter-transaction delays
  5) Press Enter -> replay WRITE candidates with original timing (via /dev/i2c-1)

Notes:
- Keeps all original console/file logging behavior.
- Uses pigpio for sniffing (GPIO2=SDA, GPIO3=SCL).
- Uses smbus2 for replay (WRITE transactions only).
"""

import argparse
import os
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import List, Tuple

import pigpio

try:
    from smbus2 import SMBus, i2c_msg

    HAVE_SMBUS2 = True
except Exception:
    HAVE_SMBUS2 = False

SDA = 2  # GPIO 2 (pin 3)
SCL = 3  # GPIO 3 (pin 5)
LOG_FILENAME = "i2c_log.txt"
I2C_BUS_NUM = 1

BASELINE_SECONDS = 10
COMMAND_SECONDS = 10


@dataclass(frozen=True)
class TxKey:
    addr: int
    rw: int  # 0 = WRITE, 1 = READ
    data: Tuple[int, ...]  # payload bytes


@dataclass
class Transaction:
    start_ts: float
    key: TxKey


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
        if os.path.exists(self.logfile_name):
            response = input(
                f"Log file '{self.logfile_name}' exists. Overwrite? (y/N): "
            )
            if response.lower() != "y":
                raise FileExistsError("Log file exists and overwrite not confirmed")

    def _timestamp(self):
        return datetime.now().strftime("%H:%M:%S.%f")[:-3]

    def log(self, msg):
        ts = self._timestamp()
        print(f"[{ts}] {msg}")
        self.logfile.write(f"[{ts}] {msg}\n")

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

    def sniff_for(self, seconds: int) -> List[Transaction]:
        """Sniff for `seconds`, log to console/file, and return parsed transactions."""
        self.log(f"Sniffing for {seconds} seconds...")
        start_time = time.time()
        out: List[Transaction] = []
        try:
            while time.time() - start_time < seconds:
                # START: SDA low while SCL high
                while not (self.pi.read(self.scl) == 1 and self.pi.read(self.sda) == 0):
                    if time.time() - start_time >= seconds:
                        raise TimeoutError
                    pass

                t0 = time.time()
                self.log("START detected")

                # Address + R/W
                addr_rw, ack = self.read_byte()
                addr = addr_rw >> 1
                rw = addr_rw & 1
                rw_str = "READ" if rw else "WRITE"
                self.log(
                    f"Master initiated transaction: Address=0x{addr:02X}, {rw_str}, ACK={ack == 0}"
                )

                payload = []
                # Read until STOP (SDA & SCL both high)
                while True:
                    if self.pi.read(self.scl) == 1 and self.pi.read(self.sda) == 1:
                        self.log("STOP detected\n")
                        break
                    byte, ackb = self.read_byte()
                    payload.append(byte)
                    self.log(f"  Data: 0x{byte:02X}, ACK={ackb == 0}")

                out.append(
                    Transaction(
                        start_ts=t0, key=TxKey(addr=addr, rw=rw, data=tuple(payload))
                    )
                )

        except TimeoutError:
            self.log(f"Reached {seconds} second capture limit.")
        except KeyboardInterrupt:
            self.log("Stopped by user.")
        return out

    def cleanup(self):
        self.logfile.close()
        self.pi.stop()

    # Original run() kept for compatibility if you want a single 20s capture:
    def run(self):
        txs = self.sniff_for(self.duration)
        self.cleanup()
        print("\nLogging complete.")
        return txs


def multiset_difference(
    new: List[Transaction], base: List[Transaction]
) -> List[Transaction]:
    """Return transactions that occur more times in `new` than in `base` (preserve order)."""
    key = lambda t: t.key
    bc = Counter(key(t) for t in base)
    nc = Counter(key(t) for t in new)
    over = {k: max(0, nc[k] - bc.get(k, 0)) for k in nc.keys()}

    kept_counts = defaultdict(int)
    results: List[Transaction] = []
    for t in sorted(new, key=lambda x: x.start_ts):
        k = key(t)
        if over.get(k, 0) > kept_counts[k]:
            results.append(t)
            kept_counts[k] += 1
    return results


def compute_intervals(txs: List[Transaction]) -> List[float]:
    """Inter-START delays between consecutive transactions."""
    if not txs:
        return []
    txs_sorted = sorted(txs, key=lambda t: t.start_ts)
    delays = [0.0]
    for i in range(1, len(txs_sorted)):
        delays.append(max(0.0, txs_sorted[i].start_ts - txs_sorted[i - 1].start_ts))
    return delays


def replay_writes(
    txs: List[Transaction], delays: List[float], bus_num: int = I2C_BUS_NUM, log=print
):
    if not HAVE_SMBUS2:
        log("smbus2 not installed. Install with: sudo pip3 install smbus2")
        return
    if len(txs) != len(delays):
        log("Internal error: tx/delay list mismatch")
        return

    # Only WRITE transactions
    writes = [
        (t, d)
        for t, d in zip(sorted(txs, key=lambda t: t.start_ts), delays)
        if t.key.rw == 0
    ]
    if not writes:
        log("No WRITE transactions to replay.")
        return

    log(f"Opening /dev/i2c-{bus_num} for replay...")
    try:
        bus = SMBus(bus_num)
    except Exception as e:
        log(f"Failed to open I2C bus: {e}")
        return

    try:
        for idx, (t, dly) in enumerate(writes, start=1):
            if dly > 0:
                time.sleep(dly)
            payload = bytes(t.key.data)
            log(
                f"WRITE #{idx} -> addr=0x{t.key.addr:02X}, bytes=[{' '.join(f'{b:02X}' for b in payload)}], delay_before={dly:.3f}s"
            )
            try:
                msg = i2c_msg.write(t.key.addr, payload)
                bus.i2c_rdwr(msg)
                log("  result: OK")
            except OSError as oe:
                err = getattr(oe, "errno", None)
                log(f"  OSError errno={err}: {oe}")
            except Exception as e:
                log(f"  Exception: {e}")
    finally:
        try:
            bus.close()
        except Exception:
            pass
        log("Replay complete.")


def main():
    parser = argparse.ArgumentParser(
        description="I2C sniffer with two-phase capture and delta replay"
    )
    parser.add_argument(
        "--logfile",
        default="i2c_log.txt",
        help="Log file name (default: i2c_log.txt)",
    )
    parser.add_argument(
        "--baseline",
        type=int,
        default=BASELINE_SECONDS,
        help=f"Baseline capture seconds (default: {BASELINE_SECONDS})",
    )
    parser.add_argument(
        "--command",
        type=int,
        default=COMMAND_SECONDS,
        help=f"Command-window capture seconds (default: {COMMAND_SECONDS})",
    )
    args = parser.parse_args()

    sniffer = I2CSniffer(logfile=args.logfile, duration=args.baseline)
    try:
        # Phase 1: Baseline
        base = sniffer.sniff_for(args.baseline)
        sniffer.log(f"Baseline captured: {len(base)} transactions.")
        sniffer.log(
            "Press Enter to start the 10s command capture; during that window, press your control(s)."
        )
        input()

        # Phase 2: Command window
        cmd = sniffer.sniff_for(args.command)
        sniffer.log(f"Command window captured: {len(cmd)} transactions.")

        # Deltas
        diffs = multiset_difference(cmd, base)
        if not diffs:
            sniffer.log("No differences found between baseline and command window.")
            return

        # Show candidates
        sniffer.log("Unique transactions (WRITE candidates marked with '*'):")
        for t in sorted(diffs, key=lambda x: x.start_ts):
            mark = "*" if t.key.rw == 0 else " "
            sniffer.log(
                f"{mark} {('WRITE' if t.key.rw==0 else 'READ ')} 0x{t.key.addr:02X}  data=[{' '.join(f'{b:02X}' for b in t.key.data)}]"
            )

        delays = compute_intervals(diffs)
        sniffer.log(
            "Ready to replay ONLY the WRITE transactions with preserved timing."
        )
        sniffer.log("Press Enter to replay, or Ctrl+C to abort.")
        input()

        # Phase 3: Replay
        replay_writes(diffs, delays, bus_num=I2C_BUS_NUM, log=sniffer.log)

    finally:
        sniffer.cleanup()
        print("\nDone.")


if __name__ == "__main__":
    main()
