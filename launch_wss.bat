

C:\Users\Arnaud\AppData\Local\herlegon\python\python.exe -m pip uninstall ^
    psutil ^
    nvidia-ml-py ^
    opencv-python ^
    numpy ^
    pillow ^
    hsys ^
    tensorrt ^
    tensorrt_cu13 ^
    tensorrt_cu13_bindings ^
    tensorrt_cu13_libs ^
    torch ^
    torchvision ^
    -y

:: rmdir /S /Q C:\Users\Arnaud\AppData\Local\herlegon\cache

:: C:\Users\Arnaud\AppData\Local\herlegon\python\python.exe wss.py --port 49990 --keep-alive --devmode
python wss.py --port 49990 --keep-alive --devmode


