#!/bin/bash

/home/adg/.local/share/herlegon/python/bin/python -m pip uninstall \
    psutil \
    nvidia-ml-py \
    -y


    # opencv-python \
    # numpy \
    # pillow \
    #

rm -rf /opt/herlegon/cache

/home/adg/.local/share/herlegon/python/bin/python wss.py --port 49990 --keep-alive --devmode


