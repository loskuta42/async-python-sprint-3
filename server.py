import asyncio

from protocol import HTTPProtocol
from utils import get_logger_for_module


logger = get_logger_for_module(__name__)


class Server:
    """
    Custom http server.
    For more info see README.md
    """

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
