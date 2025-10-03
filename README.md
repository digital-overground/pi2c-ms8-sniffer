# Pi2C MS8 Sniffer

I2C bus sniffer for Raspberry Pi using pigpio library.

## Requirements

- Raspberry Pi with GPIO access
- pigpio daemon running (`sudo pigpiod`)
- Python 3.6+

## Installation with uv

1. Install uv: `curl -LsSf https://astral.sh/uv/install.sh | sh`
2. Install dependencies: `uv sync`
3. Run the sniffer: `uv run pi2c-sniffer --logfile i2c_log.txt`

## Development

- Install in development mode: `uv sync --dev`
- Run with custom log file: `uv run pi2c-sniffer --logfile custom_log.txt`

## Legacy Installation

```bash
pip install -r requirements.txt
pip install -e .
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
