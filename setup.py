from setuptools import find_packages, setup

setup(
    name="pi2c-ms8-sniffer",
    version="1.0.0",
    description="I2C bus sniffer for Raspberry Pi using pigpio",
    author="Kyle Humphrey",
    packages=find_packages(),
    install_requires=[
        "pigpio>=1.78",
    ],
    python_requires=">=3.6",
    entry_points={
        "console_scripts": [
            "pi2c-sniffer=pi2c_sniffer.main:main",
        ],
    },
)
