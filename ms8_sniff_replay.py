#!/usr/bin/env python3
"""
ms8_sniff_replay.py

Workflow:
  1) Sniff baseline for 10s (screen connected, idle) -> in-memory
  2) Press Enter, then sniff another 10s while you press the target control(s)
  3) Compute multiset-difference: transactions that appear more in the second capture than baseline
  4) Show proposed WRITE transactions & their timings; press Enter to replay
  5) Pause sniffer, replay the unique WRITE transactions with preserved inter-transaction delays
  6) Resume sniffer, print results

Notes:
- Uses pigpio for passive sniffing (GPIO2=SDA, GPIO3=SCL).
- Uses smbus2 to actively transmit I2C writes via /dev/i2c-1.
- Only WRITE transactions can be replayed; READs are skipped.
- Timing is based on the deltas between transaction START timestamps (within the second window).

Requirements:
  sudo apt install pigpio python3-pigpio python3-smbus
  sudo pip3 install smbus2
  sudo systemctl start pigpiod

Run:
  sudo python3 ms8_sniff_replay.py
"""

import errno
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional, Tuple

import pigpio
from smbus2 import SMBus, i2c_msg

# GPIO (BCM)
SDA = 2
SCL = 3
I2C_BUS_NUM = 1

BASELINE_SECONDS = 10
COMMAND_SECONDS = 10


# ------------- Data structures -------------
@dataclass(frozen=True)
class TxKey:
    addr: int
    rw: int  # 0=WRITE, 1=READ
    data: Tuple[int, ...]  # full payload as a tuple


@dataclass
class Transaction:
    start_ts: float  # absolute time.time() at START
    key: TxKey


# ------------- Utilities -------------
def ts_hhmmss():
    return datetime.now().strftime("%H:%M:%S.%f")[:-3]


def log(msg: str):
    print(f"[{ts_hhmmss()}] {msg}")


# ------------- Sniffer -------------
class I2CSniffer:
    def __init__(self, pi: pigpio.pi, sda=SDA, scl=SCL):
        self.pi = pi
        self.sda = sda
        self.scl = scl
        self._stop = False

        self.pi.set_mode(self.sda, pigpio.INPUT)
        self.pi.set_mode(self.scl, pigpio.INPUT)

    def stop(self):
        self._stop = True

    def _wait_level(self, pin: int, level: int, timeout: float = 0.05) -> bool:
        """Wait until pin reads 'level' or timeout. Responsive to stop flag."""
        end = time.time() + timeout
        while time.time() < end:
            if self._stop:
                return False
            if self.pi.read(pin) == level:
                return True
            time.sleep(0.0002)
        return False

    def _read_bit(self) -> Optional[int]:
        """Read one I2C bit: sample SDA while SCL high (with timeouts)."""
        if not self._wait_level(self.scl, 1, timeout=0.05):
            return None
        bit = self.pi.read(self.sda)
        if not self._wait_level(self.scl, 0, timeout=0.05):
            return None
        return bit

    def _read_byte(self) -> Optional[Tuple[int, int]]:
        """Read 8 data bits + ACK bit. Returns (value, ack) where ack==0 is ACK."""
        val = 0
        for _ in range(8):
            b = self._read_bit()
            if b is None:
                return None
            val = (val << 1) | (b & 1)
        ack = self._read_bit()
        if ack is None:
            return None
        return val, ack

    def sniff_for(self, seconds: int) -> List[Transaction]:
        """Sniff for 'seconds' and return list of parsed transactions."""
        out: List[Transaction] = []
        deadline = time.time() + seconds

        log(f"Sniffing for {seconds} seconds...")
        while time.time() < deadline and not self._stop:
            # Look for START: SDA low while SCL high
            if not (self.pi.read(self.scl) == 1 and self.pi.read(self.sda) == 0):
                time.sleep(0.0005)
                continue

            start_ts = time.time()
            # addr + R/W
            hdr = self._read_byte()
            if hdr is None:
                # couldn't parse a header; skip this start
                continue
            addr_rw, ack = hdr
            addr = addr_rw >> 1
            rw = addr_rw & 1
            payload: List[int] = []

            # Read until STOP (SDA & SCL both high)
            while True:
                if self.pi.read(self.scl) == 1 and self.pi.read(self.sda) == 1:
                    break
                b = self._read_byte()
                if b is None:
                    # give up on this transaction
                    break
                val, ackb = b
                payload.append(val)

            out.append(
                Transaction(
                    start_ts=start_ts, key=TxKey(addr=addr, rw=rw, data=tuple(payload))
                )
            )
        log(f"Captured {len(out)} transactions.")
        return out


# ------------- Multiset difference & timing -------------
def multiset_difference(
    new: List[Transaction], base: List[Transaction]
) -> List[Transaction]:
    """
    Return transactions that appear more times in 'new' than in 'base'.
    Equality is by (addr, rw, full data payload). Preserves the order they
    appeared in 'new', but only as many extra occurrences as the overage count.
    """
    from collections import Counter, defaultdict, deque

    key = lambda t: t.key
    base_counts = Counter([key(t) for t in base])
    new_counts = Counter([key(t) for t in new])

    over = {k: max(0, new_counts[k] - base_counts.get(k, 0)) for k in new_counts.keys()}

    # Now walk 'new' in time order, keep as many instances as over[k]
    buckets = defaultdict(int)
    results: List[Transaction] = []
    for t in sorted(new, key=lambda x: x.start_ts):
        k = key(t)
        if over.get(k, 0) > buckets[k]:
            results.append(t)
            buckets[k] += 1
    return results


def compute_intervals(txs: List[Transaction]) -> List[float]:
    """Compute inter-transaction delays (seconds) between consecutive transactions."""
    if not txs:
        return []
    txs_sorted = sorted(txs, key=lambda t: t.start_ts)
    delays = [0.0]
    for i in range(1, len(txs_sorted)):
        delays.append(max(0.0, txs_sorted[i].start_ts - txs_sorted[i - 1].start_ts))
    return delays


# ------------- Replayer -------------
def replay_transactions(
    txs: List[Transaction], delays: List[float], bus_num: int = I2C_BUS_NUM
):
    """
    Replays only WRITE transactions (rw=0) with given inter-transaction delays.
    """
    if len(txs) != len(delays):
        raise ValueError("txs and delays length mismatch")

    if not txs:
        log("Nothing to replay.")
        return

    log(f"Opening /dev/i2c-{bus_num}...")
    try:
        bus = SMBus(bus_num)
    except Exception as e:
        log(f"Failed to open I2C bus: {e}")
        return

    try:
        for idx, (t, dly) in enumerate(
            zip(sorted(txs, key=lambda x: x.start_ts), delays), start=1
        ):
            if dly > 0:
                time.sleep(dly)

            if t.key.rw != 0:
                log(f"Skip READ  addr=0x{t.key.addr:02X}, data={len(t.key.data)} bytes")
                continue

            payload = bytes(t.key.data)
            if len(payload) == 0:
                # legal zero-length addressed write (some devices use as ping)
                msg = i2c_msg.write(t.key.addr, b"")
            else:
                msg = i2c_msg.write(t.key.addr, payload)

            log(
                f"WRITE #{idx} -> addr=0x{t.key.addr:02X}, bytes=[{' '.join(f'{b:02X}' for b in payload)}], delay_before={dly:.3f}s"
            )
            try:
                bus.i2c_rdwr(msg)
                log("  result: OK")
            except OSError as oe:
                err_no = getattr(oe, "errno", None)
                err_str = os.strerror(err_no) if err_no else str(oe)
                log(f"  OSError errno={err_no} ({err_str})  EXC={oe!r}")
            except Exception as e:
                log(f"  Exception: {e!r}")

    finally:
        try:
            bus.close()
        except Exception:
            pass
        log("Replay done.")


# ------------- Main flow -------------
def main():
    # Ensure pigpio is running
    pi = pigpio.pi()
    if not pi.connected:
        print("pigpio daemon not running. Start it with: sudo systemctl start pigpiod")
        sys.exit(1)

    sniffer = I2CSniffer(pi)
    try:
        # Phase 1: Baseline
        base = sniffer.sniff_for(BASELINE_SECONDS)
        log(
            "Baseline captured. Press Enter when ready to capture the command window (perform your action during the next 10s)..."
        )
        input()

        # Phase 2: Command window
        cmd = sniffer.sniff_for(COMMAND_SECONDS)

        # Compare / delta
        diffs = multiset_difference(cmd, base)
        if not diffs:
            log("No differences found between baseline and command window.")
            return

        # Summarize proposed replays (only WRITE)
        log("Unique transactions found (WRITE candidates):")
        for t in sorted(diffs, key=lambda x: x.start_ts):
            rw = "READ" if t.key.rw else "WRITE"
            log(
                f"  {rw} addr=0x{t.key.addr:02X}, data=[{' '.join(f'{b:02X}' for b in t.key.data)}]"
            )

        # Compute inter-transaction delays from the command window timing
        delays = compute_intervals(diffs)

        log("\nReady to replay ONLY the unique WRITE transactions preserving timing.")
        log("Press Enter to begin replay, or Ctrl+C to abort.")
        input()

        # Pause sniffing while we replay to avoid collisions
        # (Simplest approach: just stop sniffer, replay, then we're done.)
        # If you want to continue sniffing after replay, restructure to pause instead of stop.
        sniffer.stop()

        replay_transactions(diffs, delays, bus_num=I2C_BUS_NUM)

    finally:
        sniffer.stop()
        time.sleep(0.1)
        try:
            pi.stop()
        except Exception:
            pass
        log("Exiting.")


if __name__ == "__main__":
    main()
