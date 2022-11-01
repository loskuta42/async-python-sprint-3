import asyncio
import logging.config
from typing import Coroutine

import yaml

from protocol import HTTPProtocol

with open('logging_config.yaml', 'r') as f:
    config = yaml.safe_load(f.read())
    logging.config.dictConfig(config)

logger = logging.getLogger(__name__)


class Server:
    """Custom http server."""

    def __init__(self, host: str = '127.0.0.1', port: int = 8000) -> None:
        """
        :param host: server host.
        :param port: server port.
        """
        self.host = host
        self.port = port

    async def run(self):
        loop = asyncio.get_event_loop()
        server = await loop.create_server(HTTPProtocol, self.host, self.port)
        await server.serve_forever()


if __name__ == '__main__':
    server_obj = Server()
    asyncio.run(server_obj.run())
