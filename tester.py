import sys
import uuid
import json

import asyncio
import websockets

from itertools import count


async def _read_task(ws):
    counters = {}
    while True:
        packet = json.loads(await ws.recv())
        if 'connect' in packet:
            print('NEW client:', packet['connect'])
        elif 'disconnect' in packet:
            print('DEAD client:', packet['disconnect'])
        else:
            print(packet)
            sender_id = packet['my_id']
            c = packet['count']
            if sender_id not in counters:
                counters[sender_id] = c
            else:
                if c != counters[sender_id] + 1:
                    print('ERROR: SERVER DROPPED A MESSAGE!')
                    await ws.close()
                    return
                counters[sender_id] = c


async def main(room_name):
    url = f'ws://127.0.0.1:8000/ws/chat/{room_name}/'
    my_id = uuid.uuid4().hex[:8]
    print('Client starting with UUID:', my_id)
    read_task = None
    try:
        async with websockets.connect(url) as ws:
            read_task = asyncio.create_task(_read_task(ws))
            for c in count():
                packet = {'my_id': my_id, 'count': c}
                await ws.send(json.dumps(packet))
                await asyncio.sleep(0.05)
    finally:
        if read_task is not None:
            read_task.cancel()


if __name__ == '__main__':
    room_name = sys.argv[1]
    asyncio.run(main(room_name))

