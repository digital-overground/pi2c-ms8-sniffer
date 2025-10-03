.PHONY: venv install run clean

venv:
	python3 -m venv .venv
	.venv/bin/pip install --upgrade pip

install: venv
	.venv/bin/pip install -r requirements.txt

run:
	.venv/bin/python sniffer.py

run-with-log:
	.venv/bin/python sniffer.py --logfile $(LOG)

clean:
	rm -rf .venv
	rm -f *.txt

help:
	@echo "Available targets:"
	@echo "  venv     - Create virtual environment"
	@echo "  install  - Install dependencies in venv"
	@echo "  run      - Run the I2C sniffer"
	@echo "  run-with-log LOG=filename - Run with custom log file"
	@echo "  clean    - Remove venv and log files"
	@echo "  help     - Show this help"
