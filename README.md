# Pi2C MS8 Sniffer

I2C bus sniffer for Raspberry Pi using pigpio library.

## Requirements

- Raspberry Pi with GPIO access
- pigpio daemon running (`sudo pigpiod`)
- Python 3.6+

## Installation

```bash
pip install -r requirements.txt
```

Or install as package:

```bash
pip install -e .
```

## Usage

```bash
python -m pi2c_sniffer
```

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
