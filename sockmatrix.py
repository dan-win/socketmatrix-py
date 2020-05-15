"""Socket Apps Microframework with server and client tools.
Supports TCP and UNIX sockets.
Based on: https://github.com/MagicStack/uvloop/blob/master/examples/bench/echoserver.py
Dependency: uvloop
License: Apache 2 / MIT.
"""
import argparse
import asyncio
import gc
import os.path
import pathlib
import socket
import ssl
import threading
import queue as sync_queue
import re
import json
import time

PRINT = 0

import os
import logging

LOGLEVEL = os.environ.get('LOGLEVEL', 'INFO').upper()
logging.basicConfig(level=LOGLEVEL)
log = logging

class JsonConsumerProtocol(asyncio.Protocol):
    def connection_made(self, transport):
        self.exc = None
        self.transport = transport

    def connection_lost(self, exc):
        self.transport = None
        self.exc = exc

    def data_received(self, data):
        data = data.decode()
        data = json.loads(data)
        topic = data.get("topic", "")
        handler = SocketConsumer._handlers.get(topic)
        if handler:
            handler(data)
        else:
            log.error('Error 404 no such topic: %s', topic)


class JsonProducerProtocol(asyncio.Protocol):
    def __init__(self, loop):
        self.queue = None
        self.loop = loop
      
    def connection_made(self, transport):
        log.debug("Producer socket connected")
        self.exc = None
        self.queue = asyncio.Queue()
        self.transport = transport
        # Start loop
        self.loop.create_task(self.run())

    def connection_lost(self, exc):
        log.warn('The server closed the connection: %s', exc)
        self.stop()
        self.transport = None
        self.queue = None
        self.exc = exc

    def data_received(self, data):
        log.debug('Data received: {!r}'.format(data.decode()))

    async def run(self):
        log.debug("Producer Protocol: starting relay loop")
        try:
            while True:
                message = await self.queue.get()
                if message == SENTINEL or self.transport is None:
                    log.debug("Producer Protocol: breaking relay loop")
                    break
                message["user-agent"] = __name__
                serialized = json.dumps(message).encode()
                self.transport.write(serialized)
                self.transport.write(b"\n")
                log.debug("Producer Protocol: message sent [Ok]")
                await asyncio.sleep(0.5)
        except Exception as e:
            log.error("Error in Producer Protocol loop: %s", e)
    
    async def stop(self):
        if self.transport is not None:
            self.queue.put(SENTINEL)
        
    async def send_message(self, message):
        await self.queue.put(message)


class ServerManager:

    def __init__(self, *, unix_socket=None, asyncio_server=None):
        self.unix_socket = unix_socket
        self.asyncio_server = asyncio_server
        # self.interrupt = threading.Event()

    def send_close_signal(self):
        # self.interrupt.
        log.debug("Sending close signal...")
        asyncio.get_event_loop().call_soon_threadsafe(self.asyncio_server.close)

    def close(self):
        log.debug("Closing server...")
        self.asyncio_server.close()
        log.debug("Server is closed now")
        if self.unix_socket:
            import stat
            sock_path = self.unix_socket
            if os.path.exists(sock_path):
            # if stat.S_ISSOCK(os.stat(sock_path).st_mode):
                os.remove(sock_path)


class SocketConsumer:

    _handlers = {}

    def __init__(self, *, topic=None, **kwargs):
        super().__init__(**kwargs)
        if topic in SocketConsumer._handlers.keys():
            raise ValueError("Route %s already registered" % topic)
        self.topic = topic or ""

    def __call__(self, f):
        def wrapper(request_bytes):
            f(request_bytes)
        topic = self.topic
        SocketConsumer._handlers[topic] = wrapper
        return f
    
    @classmethod
    def create_server(cls, loop, args=None):
        server_context = None
        if args.ssl:
            log.info('SSL used')
            if hasattr(ssl, 'PROTOCOL_TLS'):
                server_context = ssl.SSLContext(ssl.PROTOCOL_TLS)
            else:
                server_context = ssl.SSLContext(ssl.PROTOCOL_SSLv23)
            server_context.load_cert_chain(
                (pathlib.Path(__file__).parent.parent.parent /
                    'tests' / 'certs' / 'ssl_cert.pem'),
                (pathlib.Path(__file__).parent.parent.parent /
                    'tests' / 'certs' / 'ssl_key.pem'))
            if hasattr(server_context, 'check_hostname'):
                server_context.check_hostname = False
            server_context.verify_mode = ssl.CERT_NONE

        protocol = JsonConsumerProtocol

        unix, addr = _decode_address(args.addr)
        # if args.addr.startswith('unix:'):
        #     unix = True
        #     addr = args.addr[5:]
        # else:
        #     addr = args.addr.split(':')
        #     addr[1] = int(addr[1])
        #     addr = tuple(addr)

        sock_path = None
        if unix:
            import stat
            sock_path = addr
            try:
                # if os.path.exists(addr):
                if stat.S_ISSOCK(os.stat(sock_path).st_mode):
                    os.remove(sock_path)
            except FileNotFoundError:
                pass
            except OSError as err:
                logger.warn('...Unable to check or remove stale UNIX socket '
                            '%r: %r', path, err)
            
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            try:
                sock.bind(sock_path)
            except OSError as exc:
                sock.close()
                if exc.errno == errno.EADDRINUSE:
                    msg = f'Address {sock_path!r} is already in use'
                    raise OSError(errno.EADDRINUSE, msg) from None
                else:
                    raise
            except:
                sock.close()
                raise

            server = loop.create_unix_server(protocol, sock=sock,
                                            ssl=server_context)
        else:
            server = loop.create_server(protocol, *addr,
                                        ssl=server_context)
        loop.create_task(server)
        return ServerManager(unix_socket=sock_path, asyncio_server=server)

SENTINEL = (None,)


class SocketProducer:
    _clients = []

    def __init__(self, *, socket_addr, **kwargs):
        self.queue = None
        self.addr = socket_addr
        SocketProducer._clients.append(self)
    
    def __call__(self, f):
        def wrapper(*args, **kwargs):
            response = f(*args, **kwargs)
            if self.queue is not None:
                self.queue.put_nowait(response)
            else:
                self.wait_connection()
                # Note that recursion is not infinite because wait_connection raises TimeoutError
                response = wrapper(*args, **kwargs)
            return response
        return wrapper
    
    async def create_task(self, loop):
        unix, addr = _decode_address(self.addr)
        # if self.addr.startswith('unix:'):
        #     unix = True
        #     addr = self.addr[5:]
        # else:
        #     # addr = self.addr
        #     addr = self.addr.split(':')
        #     addr[1] = int(addr[1])
        #     addr = tuple(addr)

        try:
            if unix:
                sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            else:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            
                # try:
                #     sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                # except (OSError, NameError) as e:
                #     log.warn("Error on setting sock options: %s", e)
                #     pass

            # await loop.sock_connect(sock, addr)
            sock.connect(addr)

            sock.setblocking(False)

            with sock:
                _, proto = await loop.create_connection(
                                lambda: JsonProducerProtocol(loop),
                                sock=sock)
                log.debug("Producer connection established [Ok] at %s", addr)
                self.queue = asyncio.Queue(loop=loop)
                while True:
                    message = await self.queue.get()
                    await proto.send_message(message)
                    await asyncio.sleep(0.5)

        except ConnectionRefusedError as e:
            log.error('Connection refused: %s', e)
            return 

        except Exception as e:
            log.error('Error in producer: %s: %s', addr, e)
    

    @classmethod
    def start(cls, loop):
        for instance in cls._clients:
            task = instance.create_task(loop)
            log.debug("Starting producer...")
            loop.create_task(task)

    @property
    def connected(self):
        return self.queue is not None

    def wait_connection(self, timeout=5):
        retry_interval = 0.5
        start = time.time()
        while True:
            elapsed_time = time.time() - start
            # Queue becomes non-null after connection
            if self.queue is not None:
                return elapsed_time

            if elapsed_time > timeout:
                raise TimeoutError("producer timeout error")
            else:
                time.sleep(retry_interval)



def run_server(args):

    import uvloop
    loop = uvloop.new_event_loop()

    asyncio.set_event_loop(loop)
    loop.set_debug(True)

    if args.print:
        PRINT = 1

    if hasattr(loop, 'print_debug_info'):
        loop.create_task(print_debug(loop))
        PRINT = 0

    log.info('serving on: {}'.format(args.addr))

    SocketProducer.start(loop)
    srv = SocketConsumer.create_server(loop, args)

    try:
        loop.run_forever()
    except KeyboardInterrupt:
        log.info('Closing connection')
    finally:
        if hasattr(loop, 'print_debug_info'):
            gc.collect()
            print(chr(27) + "[2J")
            loop.print_debug_info()

        loop.close()
        srv.close()

async def print_debug(loop):
    while True:
        print(chr(27) + "[2J")  # clear screen
        loop.print_debug_info()
        await asyncio.sleep(0.5, loop=loop)

def _decode_address(addr):
    if addr.startswith('unix:'):
        unix = True
        addr = addr[5:]
        addr = re.sub(r'/+', '/', addr)
        dirpath, filename = os.path.split(addr)
        if not os.path.isdir(dirpath):
            raise ValueError("Unix socket error: invalid path: %s" % addr)
        return unix, addr
    try:
        unix = False
        addr = addr.split(':')
        addr[1] = int(addr[1])
        return unix, tuple(addr)

    except Exception as e:
        raise ValueError("Invalid address: %s" % addr)

if __name__ == '__main__':
    # Simple example
    @SocketConsumer(topic="")
    def handle(data):
        print(data)
        send_message(data)
    
    @SocketProducer(socket_addr="unix:/home/danwin/Work/dev/vector.sock")
    # @SocketProducer(socket_addr="127.0.0.1:20005")
    def send_message(data):
        print("Wrapped producer called")
        return data

    parser = argparse.ArgumentParser()
    parser.add_argument('--addr', default='127.0.0.1:25000', type=str)
    parser.add_argument('--print', default=False, action='store_true')
    parser.add_argument('--ssl', default=False, action='store_true')
    args = parser.parse_args()

    run_server(args)
