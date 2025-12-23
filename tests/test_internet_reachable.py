import socket
import threading
import urllib.request
import requests
import time

def test_getaddrinfo(timeout=1.):
    result = [False]
    def check():
        try:
            socket.getaddrinfo("google.com", 80)
            result[0] = True
        except:
            pass
    thread = threading.Thread(target=check, daemon=True)
    thread.start()
    thread.join(timeout=timeout)
    return result[0]

def test_requests(timeout=1.):
    try:
        requests.head("http://google.com", timeout=timeout)
        return True
    except:
        return False

def test_socket_connect(timeout=1.):
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        sock.connect(("google.com", 80))
        sock.close()
        return True
    except:
        return False

def test_urlopen(timeout=1.):
    try:
        urllib.request.urlopen("http://google.com", timeout=timeout)
        return True
    except:
        return False

def test_create_connection(timeout=1.):
    try:
        socket.create_connection(("google.com", 80), timeout=timeout)
        return True
    except:
        return False

# Benchmark
for name, func in [
    ("getaddrinfo (threaded)", test_getaddrinfo),
    ("requests.head", test_requests),
    ("socket.connect", test_socket_connect),
    ("urllib.urlopen", test_urlopen),
    ("socket.create_connection", test_create_connection),
]:
    start = time.time()
    for _ in range(5):
        func()
    elapsed = time.time() - start
    print(f"{name}: {elapsed:.3f}s (avg: {elapsed/5:.3f}s)")
