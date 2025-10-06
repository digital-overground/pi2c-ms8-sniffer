import re
import sys
from collections import defaultdict


def parse_i2c_log(filename):
    """Parse I2C log file -> dict[address] = list of data sequences"""
    addr_pattern = re.compile(r"Address: 0x([0-9A-Fa-f]{2}) (\w+)")
    data_pattern = re.compile(r"Data: 0x([0-9A-Fa-f]{2})")
    results = defaultdict(list)

    with open(filename) as f:
        current_addr = None
        for line in f:
            addr_match = addr_pattern.search(line)
            if addr_match:
                current_addr = (addr_match.group(1), addr_match.group(2))
                results[current_addr].append([])
            elif "Data:" in line and current_addr:
                data_match = data_pattern.findall(line)
                if data_match:
                    results[current_addr][-1].extend(data_match)
    return results


def compare_logs(file1, file2):
    a = parse_i2c_log(file1)
    b = parse_i2c_log(file2)

    print(f"=== Unique or different sequences in {file1} vs {file2} ===\n")

    for addr, seqs in a.items():
        if addr not in b:
            print(f"{addr[0]} {addr[1]} — unique to {file1}")
            for seq in seqs:
                print(f"  Data: {' '.join(seq)}")
            print()
        else:
            if seqs != b[addr]:
                print(f"{addr[0]} {addr[1]} — different data between logs")
                print(f"  {file1}:")
                for seq in seqs:
                    print(f"    {' '.join(seq)}")
                print(f"  {file2}:")
                for seq in b[addr]:
                    print(f"    {' '.join(seq)}")
                print()

    print(f"=== Unique sequences in {file2} not in {file1} ===\n")
    for addr, seqs in b.items():
        if addr not in a:
            print(f"{addr[0]} {addr[1]} — unique to {file2}")
            for seq in seqs:
                print(f"  Data: {' '.join(seq)}")
            print()


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python diff_i2c_logs.py volume_down.txt volume_up.txt")
        sys.exit(1)
    compare_logs(sys.argv[1], sys.argv[2])
