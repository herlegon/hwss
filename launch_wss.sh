#!/bin/bash

/home/adg/.local/share/herlegon/python/bin/python -m pip uninstall psutil -y
python wss.py --port 49990 --keep-alive # --mode dev --show-wss-messages


