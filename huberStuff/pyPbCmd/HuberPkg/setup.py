# -*- coding: utf-8 -*-
from setuptools import setup, find_packages


setup(
    name="huber-thermostat-pkg",
    version="0.1.0",
    author="Meerstetter",
    author_email="",
    description="Python library for controlling Huber thermostats via serial communication",
    packages=find_packages(),
    classifiers=[
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
    ],
    python_requires=">=3.7",
    install_requires=[
        "pyserial>=3.5",
    ],
    extras_require={
        "dev": [
            "pytest>=7.0",
            "black>=22.0",
            "flake8>=4.0",
        ],
    },
)
