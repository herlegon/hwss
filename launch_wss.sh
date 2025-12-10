#!/bin/bash

/home/adg/.local/share/herlegon/python/bin/python -m pip uninstall \
    psutil \
    -y

rm -rf /opt/herlegon/cache

python wss.py --port 49990 --keep-alive --devmode


