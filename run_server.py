import subprocess
import os

with open("server.log", "w", encoding="utf-8") as log_file:
    log_file.write("Starting server wrapper...\n")
    log_file.flush()
    try:
        # Pass log_file directly to avoid pipe buffering issues
        process = subprocess.Popen(
            [r"C:\Users\dell\AppData\Local\Programs\Python\Python312\python.exe", "-u", "app.py"],
            stdout=log_file,
            stderr=subprocess.STDOUT
        )
        log_file.write(f"Subprocess spawned with PID: {process.pid}\n")
        log_file.flush()
        
        process.wait()
    except Exception as e:
        log_file.write(f"Exception: {e}\n")
        log_file.flush()
