from __future__ import annotations

from datetime import datetime

from client import Client


class Chat:
    def __init__(self):
        self.clients = []
        self.message_history: [(datetime, Client), str] = {}

    async def add_client_to_chat(self, added_client: Client):
        for client in self.clients:
            await client
            if client == added_client:
                self.clients.append(added_client)
                return



# TODO подумать над добавлением класса приватного чата