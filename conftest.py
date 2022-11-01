import asyncio
import multiprocessing
import time

import pytest

from client import Client
from protocol import HTTPProtocol
from server import Server


def server(host, port):
    server_obj = Server(host, port)
    asyncio.run(server_obj.run())


@pytest.fixture(autouse=True, scope="session")
def start_server():
    p = multiprocessing.Process(target=server, args=('127.0.0.1', 8000))
    p.start()
    time.sleep(3)
    yield
    p.terminate()


@pytest.fixture
def client_one():
    return Client(server_host='127.0.0.1', server_port=8000, user_name='test_client1')


@pytest.fixture
def client_two():
    return Client(server_host='127.0.0.1', server_port=8000, user_name='test_client2')


@pytest.fixture
def protocol_object():
    return HTTPProtocol()
