#!/bin/bash
# StockPilot launcher — always uses the correct Python
cd "$(dirname "$0")"
exec /home/neutra/miniforge3/bin/python -m stockpilot.cli "$@"
