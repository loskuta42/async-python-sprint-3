import asyncio
import csv
import json
import logging
import secrets
import sys

import h11

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
logger.addHandler(logging.StreamHandler(stream=sys.stdout))

ERROR_CODE_TO_MESSAGES = {
    401: 'Unauthorized. Please name yourself, add "user_name" to request body (not empty)'
         'and/or Enter your Bearer Token in "Authorization" header. '
         'If you have not have token yet, get it by POST request to endpoint '
         '"get_token"',
    400: 'User with this name is already exists'
}

MESSAGES_FOR_USER = {
    'type': {
        'warning': {
            'had_token': 'You have got token already.',
            'no_data': 'no request body'
        }
    }
}


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
                    self._request_processing(self.connection, event)
                elif (
                        isinstance(event, h11.ConnectionClosed)
                        or event is h11.NEED_DATA or event is h11.PAUSED
                ):
                    break
            except RuntimeError:
                logger.exception('exception in data_received')

        if self.connection.our_state is h11.DONE:  # TODO возможно понадобиться h11.MUST_CLOSE
            logger.info('Close connection %s', self.transport.get_extra_info('peername'))
            self.transport.close()

    def _request_processing(self, connection, request_event):
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
                data = json.loads(event.data.decode('utf-8'))
                user_name = data.get('user_name', None)
                if not user_name:
                    self._send_error(401)
                elif request_event.target == b'/get_token':
                    self._send_token(user_name)
                elif request_event.target == b'/connect':
                    try:
                        chat_name = data['chat_name']
                    except KeyError:
                        chat_name = 'public'
                    self._send_response_for_connect_endpoint(chat_name)
                elif request_event.target == b'/send':
                    chat_name = data.get('chat_name', None)

                    self._send_response_for_send_endpoint(chat_name)

    def _send_response_with_OK_code(self, body: bytes, headers: list):
        response = h11.Response(status_code=200, headers=headers)
        self.send(response)
        self.send(h11.Data(data=body))
        self.send(h11.EndOfMessage())

    def send_response_for_post(self, data_event, request_event):
        body = data_event.data
        d_body = body.decode('utf-8')
        print(json.loads(d_body))
        headers = self._get_headers_for_json_body(body)
        self._send_response_with_OK_code(body, headers)

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
                when, user_name, massage = row
                temp_dict['massages'].append(
                    {
                        'datetime': when,
                        'username': user_name,
                        'massage': massage
                    }
                )
        response_body_unicode = json.dumps(
            temp_dict, sort_keys=True, indent=4, separators=(',', ': ')
        )
        response_body_bytes = response_body_unicode.encode('utf-8')
        return response_body_bytes

    def _send_response_for_connect_endpoint(self, chat_name):
        if not chat_name:
            body = self._get_public_massages()
        else:
            body = self._get_private_massages(user_name)
        headers = self._get_headers_for_json_body(body)
        self._send_response_with_OK_code(body, headers)

    def _send_error(self, error_code):
        body = self._get_one_key_strbody('error', ERROR_CODE_TO_MESSAGES[error_code])
        headers = self._get_headers_for_json_body(body)
        response = h11.Response(status_code=error_code, headers=headers)
        self.send(response)
        self.send(h11.Data(data=body))
        self.send(h11.EndOfMessage())

    def _send_info(self, message):
        body = self._get_one_key_strbody('info', message)
        headers = self._get_headers_for_json_body(body)
        self._send_response_with_OK_code(body, headers)

    def _send_token(self, user_name):
        users = []  # TODO добавить хранилище с пользователями
        tokens = []  # TODO поставить в соответствие пользователям токены

        if user_name in users:
            self._send_info(MESSAGES_FOR_USER['type']['warning']['had_token'])
        token = secrets.token_hex(16)
        while token in tokens:
            token = secrets.token_hex(16)
        tokens.append(token)

        body = self._get_one_key_strbody('token', token)
        headers = self._get_headers_for_json_body(body)
        self._send_response_with_OK_code(body, headers)

    @staticmethod
    def _get_one_key_strbody(key: str, value: str):
        return json.dumps(
            {
                key: value
            },
            sort_keys=True,
            indent=4,
            separators=(',', ': ')
        ).encode('uts-8')

    @staticmethod
    def _get_headers_for_json_body(body):
        return [
            ('content-type', 'application/json'),
            ('content-length', str(len(body))),
        ]

async def main(host, port):
    loop = asyncio.get_running_loop()
    server = await loop.create_server(HTTPProtocol, host, port)
    await server.serve_forever()


asyncio.run(main('127.0.0.1', 5000))
