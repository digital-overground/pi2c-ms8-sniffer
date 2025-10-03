# Pi2C MS8 Sniffer

I2C bus sniffer for Raspberry Pi using pigpio library.

## Requirements

- Raspberry Pi with GPIO access
- pigpio daemon running (`sudo pigpiod`)
- Python 3.6+

## Installation

```bash
make install
```

## Usage

```bash
make run
```

Or run directly:
```bash
.venv/bin/python sniffer.py
```

With custom log file:
```bash
make run-with-log LOG=custom_log.txt
```

Compare two log files:
```bash
make compare LOG1=log1.txt LOG2=log2.txt
```

## Available Commands

- `make venv` - Create virtual environment
- `make install` - Install dependencies
- `make run` - Run the I2C sniffer
- `make compare LOG1=file1 LOG2=file2` - Compare two log files
- `make clean` - Remove venv and log files

## Features

- Real-time I2C bus monitoring
- START/STOP condition detection
- Address and data logging
- ACK/NACK status reporting
- Timestamped log output

## Configuration

Default GPIO pins:
- SDA: GPIO 2 (pin 3)
- SCL: GPIO 3 (pin 5)

Modify `pi2c_sniffer/config.py` to change pin assignments.
