from __future__ import annotations

from typing import Optional
from asyncio import StreamReader, StreamWriter
from chat import Chat


# import asyncio
# import aiohttp


class Client:
    def __init__(
            self,
            name: str,
            address:str,
            reader: StreamReader,
            writer: StreamWriter,
            server_host="127.0.0.1",
            server_port=8000
    ):
        self.name = name
        self.server_host = server_host
        self.server_port = server_port
        self.reader = reader
        self.writer = writer
        self.address:Optional[str] = address
        self.chats = {}

    async def send(self, message_to: Client, message: str=''):
        pass

    async def start_chat(self, receiver_obj):
        if receiver_obj.address not in self.chats:
            self.chats[receiver_obj.address] = []
        # while True:

