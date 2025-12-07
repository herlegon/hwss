
import asyncio
import websockets
import json
import logging

async def test_shutdown():
    uri = "ws://127.0.0.1:49990"
    try:
        async with websockets.connect(uri) as websocket:
            print("Connected to server")
            msg = {"cmd": "shutdown"}
            print(f"Sending: {msg}")
            await websocket.send(json.dumps(msg))
            print("Message sent")
            
            # Wait to see if connection is closed by server
            try:
                await websocket.wait_closed()
                print("Connection closed by server")
            except Exception as e:
                print(f"Wait closed exception: {e}")

    except Exception as e:
        print(f"Connection failed: {e}")

if __name__ == "__main__":
    asyncio.run(test_shutdown())
