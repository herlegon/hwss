echo off
del /Q C:\Users\Arnaud\AppData\Local\herlegon\python\bootstrap_*.pyd
copy .\bootstrap\*.py C:\Users\Arnaud\AppData\Local\herlegon\python\
copy .\hwss\wss.py C:\Users\Arnaud\AppData\Local\herlegon\python\modules\hwss\

copy .\hwss\*.py C:\Users\Arnaud\AppData\Local\herlegon\python\modules\hwss\
copy ..\hinstall\hinstall\*.py C:\Users\Arnaud\AppData\Local\herlegon\python\modules\hinstall\


C:\Users\Arnaud\AppData\Local\herlegon\python\python.exe ^
    C:\Users\Arnaud\AppData\Local\herlegon\python\bootstrap.py
