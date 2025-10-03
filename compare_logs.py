#!/usr/bin/env python3
"""
Compare two I²C log files and highlight differences in commands.

Usage:
  python3 compare_logs.py <log1> <log2>
"""

import re
import sys
from difflib import unified_diff
from pathlib import Path


def parse_log(filepath):
    """Extract I2C transactions from a log file."""
    pattern_addr = re.compile(r"Address: 0x([0-9A-F]{2}) (\w+), ACK=(True|False)")
    pattern_data = re.compile(r"Data: 0x([0-9A-F]{2}), ACK=(True|False)")

    transactions = []
    with open(filepath) as f:
        lines = f.readlines()

    current = []
    for line in lines:
        line = line.strip()
        if "START detected" in line:
            current = ["START"]
        elif match := pattern_addr.search(line):
            addr, rw, ack = match.groups()
            current.append(f"ADDR:{addr}:{rw}:{ack}")
        elif match := pattern_data.search(line):
            val, ack = match.groups()
            current.append(f"DATA:{val}:{ack}")
        elif "STOP" in line:
            current.append("STOP")
            transactions.append(current)
            current = []

    return transactions


def flatten(transactions):
    """Flatten transactions into one list of tokens."""
    return [token for t in transactions for token in t]


def main():
    if len(sys.argv) < 3:
        print("Usage: python3 compare_logs.py <log1> <log2>")
        sys.exit(1)

    file1 = Path(sys.argv[1])
    file2 = Path(sys.argv[2])

    if not file1.exists() or not file2.exists():
        print("Error: One or both log files not found.")
        sys.exit(1)

    tx1 = flatten(parse_log(file1))
    tx2 = flatten(parse_log(file2))

    diff = unified_diff(tx1, tx2, fromfile=file1.name, tofile=file2.name, lineterm="")

    print("\n🧩 Comparing I²C logs...")
    print(f"File 1: {file1}")
    print(f"File 2: {file2}\n")

    has_diff = False
    for line in diff:
        has_diff = True
        if line.startswith("+"):
            print(f"\033[92m{line}\033[0m")  # green for additions
        elif line.startswith("-"):
            print(f"\033[91m{line}\033[0m")  # red for removals
        elif line.startswith("@@"):
            print(f"\033[94m{line}\033[0m")  # blue for context
        else:
            print(line)

    if not has_diff:
        print("✅ No differences detected — identical I²C transactions.")


if __name__ == "__main__":
    main()
