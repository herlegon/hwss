


the scenario is the following:

1) the frontend starts a subprocess to catch the stdin/stdout:
`self._backend_process = subprocess.Popen(["python", "bootstrap.py"], ...)`

2) then the bootstrap auto-update and restart if needed.
at the end, it has to run the script `modules/hwss/hwss.py`

3) the `hwss.py` starts a websocket server.

I would like that `self._backend_process` be alive until the end,  when websocket server is asked to stop because i need to catch the stdout/stderr

i already have the code of each script, but i don't know what kind of calls i have to use for each step

