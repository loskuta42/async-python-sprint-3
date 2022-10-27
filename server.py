# import asyncio
# import aiohttp
import asyncio
import logging
import sys
from asyncio import StreamReader, StreamWriter
from client import Client

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
logger.addHandler(logging.StreamHandler(stream=sys.stdout))


class Server:
    def __init__(self, host: str = '127.0.0.1', port=8000):
        self.host = host
        self.port = port
        self._clients = {}
        self._chats = {}

    async def listen(self, reader: StreamReader, writer: StreamWriter):
        address = writer.get_extra_info('peername')
        logger.info('Start serving %s', address)
        if address not in self._clients:
            writer.write(
                f'Hello! Seems like you first time there. Please name yourself:\n'
                .encode('utf-8')
            )
            name = (await reader.readline()).decode('utf-8').rstrip('/n')
            client = Client(
                name=name,
                address=address,
                reader=reader,
                writer=writer,
                server_host=self.host,
                server_port=self.port)
            client.reader = reader
            client.writer = writer
            writer.write(f'Hello {name}!'.encode('utf-8'))
            self._clients[address] = client
        cur_client = self._clients[address]
        while True:
            writer.write('Open chat with:'.encode('utf-8'))
            receiver_name = (await reader.readline()).decode('utf-8').rstrip('/n')
            receiver_address, receiver_obj = await self._find_client_by_name(receiver_name)
            if not receiver_obj:
                writer.write('Can not find this username. Try again.'.encode('utf-8'))
                continue
            else:
                writer.write(f'Openning chat with {receiver_name}'.encode('utf-8'))
                await cur_client.start_chat(receiver_obj)

    async def _find_client_by_name(self, sender_name):
        for key, value in self._clients.items():
            client_name = await value.name
            if client_name == sender_name:
                return key, client_name
        return None
