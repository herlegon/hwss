#!/bin/bash

/home/adg/.local/share/herlegon/python/bin/python -m pip uninstall \
    safetensors \
    torch \
    torchvision \
    onnx \
    onnxruntime \
    -y


    # opencv-python \
    # numpy \
    # pillow \
    #

rm -rf /opt/herlegon/cache

/home/adg/.local/share/herlegon/python/bin/python ./hwss/wss.py --port 49990 --keep-alive --devmode


