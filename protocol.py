import asyncio
import csv
import json
import logging
import sys

import h11

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
logger.addHandler(logging.StreamHandler(stream=sys.stdout))


class HTTPProtocol(asyncio.Protocol):
    def __init__(self):
        self.connection = h11.Connection(h11.SERVER)
        self.active_clients = {}

    def connection_made(self, transport):
        self.transport = transport
        logger.info('Start serving %s', transport.get_extra_info('peername'))

    def data_received(self, data):
        self.connection.receive_data(data)
        while True:
            event = self.connection.next_event()
            try:
                if isinstance(event, h11.Request):
                    self.send_response(self.connection, event)
                elif (
                        isinstance(event, h11.ConnectionClosed)
                        or event is h11.NEED_DATA or event is h11.PAUSED
                ):
                    break
            except RuntimeError:
                logger.exception('exception in data_received')

        if self.connection.our_state is h11.DONE: # TODO возможно понадобиться h11.MUST_CLOSE
            logger.info('Close connection %s', self.transport.get_extra_info('peername'))
            self.transport.close()

    def send_response(self, connection, request_event):
        if request_event.method not in [b'GET', b'POST']:
            logger.error('runtime_error')
            raise RuntimeError('unsupported method')
        while True:
            event = connection.next_event()
            if isinstance(event, h11.EndOfMessage):
                break
            try:
                assert isinstance(event, h11.Data)
            except AssertionError:
                logger.error('AssertionError')
                logger.exception('exception in sending response')
                break
            if request_event.method == b'POST':
                if request_event.target == b'/connect':
                    data =
                    self._send_response_for_connect_endpoint()

        # body = b"%s %s" % (event.method.upper(), event.target)
        # headers = [
        #     ('content-type', 'application/json'),
        #     ('content-length', str(len(body))),
        # ]
        # response = h11.Response(status_code=200, headers=headers)
        # self.send(response)
        # self.send(h11.Data(data=body))
        # self.send(h11.EndOfMessage())

    def send_response_for_post(self, data_event, request_event):
        body = data_event.data
        d_body = body.decode('utf-8')
        print(json.loads(d_body))
        headers = [
            ('content-type', 'application/json'),
            ('content-length', str(len(body))),
        ]
        response = h11.Response(status_code=200, headers=headers)
        self.send(response)
        self.send(h11.Data(data=body))
        self.send(h11.EndOfMessage())

    def send(self, event):
        data = self.connection.send(event)
        self.transport.write(data)

    @staticmethod
    def _get_public_massages(messages_number=20):
        with open('datafiles/public_chat.csv') as file:
            temp_dict = {'massages': []}
            reader = csv.reader(file, delimiter=',')
            messages_number -= 1
            for ind, row in enumerate(reader):
                if ind == messages_number:
                    break
                when, who, massage = row
                temp_dict['massages'].append(
                    {
                        'datetime': when,
                        'username': who,
                        'massage': massage
                    }
                )
        response_body_unicode = json.dumps(
            temp_dict, sort_keys=True, indent=4, separators=(',', ': ')
        )
        response_body_bytes = response_body_unicode.encode('utf-8')
        return response_body_bytes

    def _send_response_for_connect_endpoint(self):
        body = self._get_public_massages()
        headers = [
            ('content-type', 'application/json'),
            ('content-length', str(len(body))),
        ]
        response = h11.Response(status_code=200, headers=headers)
        self.send(response)
        self.send(h11.Data(data=body))
        self.send(h11.EndOfMessage())


async def main(host, port):
    loop = asyncio.get_running_loop()
    server = await loop.create_server(HTTPProtocol, host, port)
    await server.serve_forever()


asyncio.run(main('127.0.0.1', 5000))
