#!/bin/bash

/home/adg/.local/share/herlegon/python/bin/python -m pip uninstall \
    psutil \
    nvidia-ml-py \
    opencv-python \
    numpy \
    pillow \
    -y

rm -rf /opt/herlegon/cache

/home/adg/.local/share/herlegon/python/bin/python wss.py --port 49990 --keep-alive --devmode


