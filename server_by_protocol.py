import asyncio
import logging
import sys

from protocol import HTTPProtocol

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
logger.addHandler(logging.StreamHandler(stream=sys.stdout))


class Server:
    def __init__(self, host: str = '127.0.0.1', port=8000):
        self.host = host
        self.port = port

    async def run(self):
        loop = asyncio.get_event_loop()
        server = await loop.create_server(HTTPProtocol, self.host, self.port)
        await server.serve_forever()


if __name__ == '__main__':
    server_obj = Server()
    asyncio.run(server_obj.run())
