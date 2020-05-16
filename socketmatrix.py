"""Socket Apps Microframework with server and client tools.
Supports TCP and UNIX sockets.
Based on:
https://github.com/MagicStack/uvloop/blob/master/examples/bench/echoserver.py
Dependency: uvloop
License: Apache 2 / MIT.
"""
import argparse
import asyncio
import os.path
import pathlib
import socket
import ssl
import re
import json
import time
# import signal
import os
import stat
import logging
import errno
from enum import Enum

LOGLEVEL = os.environ.get('LOGLEVEL', 'INFO').upper()
logging.basicConfig(level=LOGLEVEL)
log = logging

PRINT = 0


class ServiceState(Enum):
    IDLE = 0
    STARTING = 1
    RUNNING = 2
    STOPPING = 3
    DONE = 4
    ERROR = -1


class JsonConsumerProtocol(asyncio.Protocol):
    def __init__(self, loop):
        self.loop = loop

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
        self.runner = None

    def connection_made(self, transport):
        log.debug("Producer socket connected")
        self.exc = None
        self.queue = asyncio.Queue()
        self.transport = transport
        # Start loop
        self.runner = self.loop.create_task(self.run())

    def connection_lost(self, exc):
        log.warn('The server closed the connection: %s', exc)
        self.stop()
        self.transport = None
        self.queue = None
        self.exc = exc
        if self.runner is not None:
            self.runner.cancel()
            self.runner = None

    def data_received(self, data):
        log.debug('Data received: {!r}'.format(data.decode()))

    async def run(self):
        log.debug("Producer Protocol: starting relay loop")
        try:
            while True:
                if self.transport is None:
                    await asyncio.sleep(1)
                    continue
                message = await self.queue.get()
                if message == SENTINEL or self.transport is None:
                    log.debug("Producer Protocol: breaking relay loop")
                    break
                message["user-agent"] = __name__
                serialized = json.dumps(message).encode()
                while True:
                    try:
                        self.transport.write(serialized)
                        self.transport.write(b"\n")
                    except BlockingIOError:
                        continue
                    break

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

    # def send_close_signal(self):
    #     # self.interrupt.
    #     log.debug("Sending close signal...")
    #     asyncio.get_event_loop().call_soon_threadsafe(self.asyncio_server.close)

    async def close(self):
        asyncio_server = self.asyncio_server.result()  # Unwrap task
        log.debug("Closing server...")
        asyncio_server.close()
        await asyncio_server.wait_closed()
        log.debug("Server is closed now")
        if self.unix_socket:
            sock_path = self.unix_socket
            if os.path.exists(sock_path):
                os.remove(sock_path)
        return True


class SocketConsumer:

    _handlers = {}
    _srv = None

    def __init__(self, *, topic=None, **kwargs):
        super().__init__(**kwargs)
        if topic in SocketConsumer._handlers.keys():
            raise ValueError("Route %s already registered" % topic)
        self.topic = topic or ""

    def __call__(self, f):
        def wrapper(request_bytes):
            return f(request_bytes)
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

        def protocol_factory():
            return JsonConsumerProtocol(loop)

        unix, addr = _decode_address(args.addr)

        sock_path = None
        if unix:
            sock_path = addr
            try:
                # if os.path.exists(addr):
                if stat.S_ISSOCK(os.stat(sock_path).st_mode):
                    os.remove(sock_path)
            except FileNotFoundError:
                pass
            except OSError as err:
                log.warning('...Unable to check or remove stale UNIX socket '
                            '%r: %r', sock_path, err)

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
            except Exception:
                sock.close()
                raise

            server = loop.create_unix_server(
                        protocol_factory,
                        sock=sock,
                        ssl=server_context)
        else:
            server = loop.create_server(
                        protocol_factory,
                        *addr,
                        ssl=server_context)

        srv_task = loop.create_task(server)
        # server_obj = loop.run_until_complete(server)
        cls._srv = ServerManager(
                unix_socket=sock_path,
                asyncio_server=srv_task
            )
        return cls._srv

    @classmethod
    async def stop(cls, loop):
        if cls._srv is not None:
            # loop.stop()
            await cls._srv.close()
            cls._srv = None


SENTINEL = (None,)


class SocketProducer:
    _clients = []

    def __init__(self, *, socket_addr, **kwargs):
        self.queue = None
        self.addr = socket_addr
        self.loop = None
        SocketProducer._clients.append(self)

    def __call__(self, f):
        def wrapper(*args, **kwargs):
            response = f(*args, **kwargs)
            if self.queue is not None:
                print("PRODUCER: putting to queue")
                self.queue.put_nowait(response)
            elif self.loop is not None:
                print("PRODUCER: waiting for connection .........")
                res = self.loop.run_until_complete(self.wait_connection())
                print(res, dir(res))
                # Note that recursion is not infinite
                # because wait_connection raises TimeoutError
                response = wrapper(*args, **kwargs)
            else:
                raise ConnectionRefusedError(
                    "Cannot produce message before services start")
            return response
        return wrapper

    async def create_task(self, loop):
        unix, addr = _decode_address(self.addr)

        try:
            if unix:
                sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            else:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                # try:
                #     sock.setsockopt(
                #       socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
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
                self.loop = loop
                while True:
                    message = await self.queue.get()
                    await proto.send_message(message)
                    # Do that only after passing message to protocol handler
                    # (in order to allow stop protocol loops also)
                    if message == SENTINEL:
                        break
                    await asyncio.sleep(0.5)

            self.queue = None
            log.info("Producer - closing connection at %s", addr)

        except ConnectionRefusedError as e:
            log.error('Connection refused: %s', e)
            return

        except Exception as e:
            log.error('Error in producer: %s: %s', addr, e)

    async def try_send_message(self, message):
        if self.queue is not None:
            await self.queue.put(message)

    @classmethod
    def start(cls, loop):
        for instance in cls._clients:
            task = instance.create_task(loop)
            log.debug("Starting producer...")
            loop.create_task(task)

    @classmethod
    async def stop(cls, loop):
        for instance in cls._clients:
            log.debug("Stopping producers...")
            await instance.try_send_message(SENTINEL)

    @property
    def connected(self):
        return self.queue is not None

    async def wait_connection(self, timeout=5):
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
                await asyncio.sleep(retry_interval)


class StateError(BaseException):
    "Invalid operation for current state"


class ServiceMatrix:

    _STOP_HANDLE = None
    loop = None
    _state = ServiceState.IDLE

    @classmethod
    def cleanup(cls):
        SocketConsumer._handlers = {}
        SocketConsumer._srv = None
        SocketProducer._clients = []
        cls._STOP_HANDLE = None
        cls.loop = None
        cls._state = ServiceState.IDLE

    @classmethod
    def start_services(cls, args, *, loop=None):
        if cls._state != ServiceState.IDLE:
            raise StateError()

        if loop is None:
            import uvloop
            loop = uvloop.new_event_loop()

            asyncio.set_event_loop(loop)
            loop.set_debug(True)

        cls.loop = loop

        def handle_exception(loop, exc_context):
            print("Async Error: ", exc_context)
            log.error(
                "Async Error: %s| %r | %s", exc_context["message"],
                exc_context.get("exception"),
                exc_context.get("source_traceback"))

        loop.set_exception_handler(handle_exception)

        SocketConsumer.create_server(loop, args)
        SocketProducer.start(loop)
        cls._state = ServiceState.STARTING
        return loop

    @classmethod
    def run_services(cls):
        if cls._state != ServiceState.STARTING:
            raise StateError()

        stop_event = asyncio.Event(loop=cls.loop)
        cls._STOP_HANDLE = stop_event

        # def catch_signal(signal, loop):
        #     log.info('Got signal: %s', signal)
        #     # loop.call_soon_threadsafe(stop_event.set)
        #     # await close_all(loop)
        #     loop.create_task(close_all(loop))

        # import functools
        # signals = (signal.SIGHUP, signal.SIGTERM, signal.SIGINT)
        # for s in signals:
        #     loop.add_signal_handler(
        #         s, functools.partial(catch_signal, s, loop))

        async def close_all(loop):
            print("Exit signal occurs........")
            # Run exit code...

            await SocketProducer.stop(loop)
            await SocketConsumer.stop(loop)

            print("Exit signal occurs........ 1")

            # loop.run_until_complete(srv.close())
            tasks = [
                    t for t in asyncio.Task.all_tasks()
                    if t is not asyncio.Task.current_task()
                ]

            print("Exit signal occurs........ 2")

            [task.cancel() for task in tasks]
            log.info('Cancelling %s outstanding tasks', len(tasks))
            await asyncio.gather(*tasks, return_exceptions=True)
            loop.stop()
            loop.close()
            log.info('All pending tasks are finished now')

            log.info("Done")
            cls._STOP_HANDLE = None
            cls._state = ServiceState.DONE

        async def main(loop):
            await stop_event.wait()
            await close_all(loop)

        cls.loop.create_task(main(cls.loop))
        cls._state = ServiceState.RUNNING
        cls.loop.run_forever()

    @classmethod
    def stop_services(cls):
        if not cls._STOP_HANDLE:
            return
        cls._STOP_HANDLE.set()
        # if hasattr(loop, 'print_debug_info'):
        #     gc.collect()
        #     print(chr(27) + "[2J")
        #     loop.print_debug_info()

        # SocketProducer.stop(loop)
        # SocketConsumer.stop(loop)
        # # loop.run_until_complete(srv.close())
        # tasks = [t for t in asyncio.Task.all_tasks() if t is not
        #         asyncio.Task.current_task()]

        # [task.cancel() for task in tasks]
        # log.info('Cancelling %s outstanding tasks', len(tasks))
        # loop.stop()
        # loop.run_until_complete(
        #   asyncio.gather(*tasks, return_exceptions=True))

        # loop.close()

    @classmethod
    def run(cls, args):

        cls.start_services(args)

        log.info('serving on: {}'.format(args.addr))

        try:
            cls.run_services()
        except KeyboardInterrupt:
            log.info('Closing connection')
        finally:
            cls.stop_services()


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

    except Exception:
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

    ServiceMatrix.run(args)
