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

from sockmatrix import (
    SocketConsumer,
    SocketProducer
)

class config:
    def __init__(self, addr):
        self.addr = addr
        self.print = False
        self.ssl = False

class test_unix_socket(unittest.TestCase):

    def setUp(self):
        import sockmatrix 
        self.sockmatrix = sockmatrix

        from os.path import (expanduser, join)
        # # home = expanduser("~")
        self.HOME_DIR = expanduser("~")
        self.sock_path = 'unix:' + join(self.HOME_DIR, 'sockmatrix.sock')

        print("Socket path: ", self.sock_path)

        self.conf = config(self.sock_path)

        # parser = argparse.ArgumentParser()
        # parser.add_argument('--addr', default=f'unix:{self.sock_path}', type=str)
        # parser.add_argument('--print', default=False, action='store_true')
        # parser.add_argument('--ssl', default=False, action='store_true')

        # self.conf = parser.parse_args(['--addr', f'unix:{self.sock_path}'])

        # import uvloop
        # loop = uvloop.new_event_loop()

        # asyncio.set_event_loop(loop)
        # loop.set_debug(True)
        # self.loop = loop

    def tearDown(self):
        # self.loop.close()
        pass


    # @timeout_decorator.timeout(5, timeout_exception=StopIteration)
    def test_exit_with_empty_queue(self):
        conf = self.conf

        async def pass_stop_signal(srv_man, sync_evt):
            while True:
                await asyncio.sleep(1)
                if sync_evt.is_set():
                    srv_man.close()
                    return

        def services_thread(*, conf, evt_stop):
            import uvloop
            loop = uvloop.new_event_loop()

            asyncio.set_event_loop(loop)
            loop.set_debug(True)
            try:
                print(type(conf), conf, type(conf.addr), conf.addr)
                print("Passing arguments: ", conf, evt_stop)
                srv = SocketConsumer.create_server(loop, conf)
                SocketProducer.start(loop)

                # loop.create_task()

                print("[1] Loop starting...")
                loop.run_until_complete(pass_stop_signal(srv, evt_stop))
                print("[2] Loop done")
            finally:
                loop.close()
                print("[3] Loop closed")
            

        print(70 * '+')
        results = []

        @SocketConsumer(topic="")
        def handle(data):
            results.append(data)

        @SocketProducer(socket_addr=self.sock_path)
        def send_message(data):
            return data

        evt_stop = threading.Event()
        handle = threading.Thread(target=services_thread, kwargs=dict(conf=conf, evt_stop=evt_stop))
        handle.start()

        # SocketProducer.wait_connection(3)
        for i in range(10,16):
            send_message(i)

        # Send stop signal after delay        
        threading.Timer(5, evt_stop.set).start()

        handle.join()

        print("Result in test: ", results)
        # self.assertEqual(e_result, 0)

