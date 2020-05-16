# coding: utf-8
import unittest
from unittest.mock import patch
from contextlib import contextmanager

# import amqrotor

import queue as sync_queue
# import timeout_decorator
import threading
import argparse
import asyncio

from socketmatrix import (
    SocketConsumer,
    SocketProducer,
    ServiceMatrix,
    # start_services,
    # run_services,
    # stop_services
)

class config:
    def __init__(self, addr):
        self.addr = addr
        self.print = False
        self.ssl = False

class test_unix_socket(unittest.TestCase):

    def setUp(self):
        ServiceMatrix.cleanup()


    def tearDown(self):
        ServiceMatrix.cleanup()


    # @timeout_decorator.timeout(5, timeout_exception=StopIteration)
    def test_channel_integrity_unix(self):
        # Prepare test config

        from os.path import (expanduser, join)
        home_dir = expanduser("~")
        sock_path = 'unix:' + join(home_dir, 'sockmatrix.sock')
        print("Socket path: ", sock_path)
        conf = config(sock_path)

        print(70 * '+')
        results = []

        messages_set = range(10, 16)

        @SocketConsumer(topic="")
        def handle(data):
            print("GOT", data)
            results.append(data)

        @SocketProducer(socket_addr=sock_path)
        def send_message(data):
            return data

        async def make_messages(loop):
            await asyncio.sleep(1, loop=loop)
            for i in messages_set:
                print("SEND", i)
                try:
                    send_message(dict(data=i))
                except Exception as e:
                    print("Error in producer: ", e)
    
                await asyncio.sleep(0.1, loop)

            # Pass quit signal after 3 second
            await send_stop(loop, 3)

        # import uvloop
        # loop = uvloop.new_event_loop()

        # asyncio.set_event_loop(loop)
        loop = asyncio.get_event_loop()
        loop.set_debug(True)

        loop = ServiceMatrix.start_services(conf, loop=loop)
        
        loop.create_task(make_messages(loop))

        print("[1] Loop starting...")
        ServiceMatrix.run_services()
        print("[2] Loop done")

        print("Result in test: ", results)

        values = [r['data'] for r in results]
        values.sort()
        self.assertListEqual(values, list(messages_set))


# Helpers
async def send_stop(loop, delay):
    await asyncio.sleep(delay, loop=loop)
    print("Sending stop...")
    try:
        ServiceMatrix.stop_services()
    except Exception as e:
        print("Error on stop_services: ", e)

