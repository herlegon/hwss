echo off

:: Bootstrap
del /Q C:\Users\Arnaud\AppData\Local\herlegon\python\bootstrap_*.pyd
copy .\bootstrap\*.py C:\Users\Arnaud\AppData\Local\herlegon\python\

:: Deploy hwss
copy .\hwss\*.py C:\Users\Arnaud\AppData\Local\herlegon\python\Modules\hwss\
copy .\hwss\wss.py C:\Users\Arnaud\AppData\Local\herlegon\python\Modules\hwss\

:: Deploy hinstall
copy ..\hinstall\hinstall\*.py C:\Users\Arnaud\AppData\Local\herlegon\python\Modules\hinstall\

:: Start server
C:\Users\Arnaud\AppData\Local\herlegon\python\python.exe ^
    C:\Users\Arnaud\AppData\Local\herlegon\python\bootstrap.py
