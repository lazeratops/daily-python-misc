import argparse
import dataclasses
import time
from urllib.parse import urlparse
from daily import CallClient, Daily, EventHandler
import requests
import polling2

@dataclasses.dataclass
class Room:
    name: str
    room_url: str
    api_url: str
    token: str

class Client(EventHandler):
    _room: Room
    _cc: CallClient
    _api_key: str
    _done: bool

    def __init__(self, room_url: str, api_key: str):
        self._api_key = api_key
        self._room = self._get_room(room_url, api_key)
        self._cc = CallClient(self)
        self._done = False

    @property
    def done(self):
        return self._done

    def wait(self):
        try:
            polling2.poll(
                target=self._get_participant_count,
                check_success=lambda count: count > 0,
                step=3,
                timeout=300)
        except polling2.TimeoutException:
            raise Exception('Timed out waiting for participants to join')


    def _on_joined(self, _, error):
        if error:
            raise Exception(f'Failed to join room: {error}')
        
        print("joined room")
        counts = self._cc.participant_counts()
        print("post-join counts:", counts)
        count = counts['present']
        print("count.", count)
        if count < 1:
            raise Exception(f'Expected 1 present participant, got {count}')


    def _get_meeting_token(self, r: Room) -> str:
        url = f'{r.api_url}/meeting-tokens'

        res = requests.post(url,
                headers={'Authorization': f'Bearer {self._api_key}'},
                json={'properties':
                      {'room_name': r.name,
                       'is_owner': True,
                       'exp': time.time() * 300,
                       'permissions': {
                           'hasPresence': False,
                       },
                }})

        if not res.ok:
            raise Exception(f'Failed to get meeting token: {res.status_code}, {res.text}')

        meeting_token = res.json()['token']
        return meeting_token

    def on_participant_left(self, participant, reason):
        counts = self._cc.participant_counts()['present']
        if counts == 1:
            print("Robot is last in meeting; leaving")
            self._cc.leave(completion=self._on_left)
        

    def join(self):
        self.wait()
        # Once we get here presence endpoint will have said
        # there's at least one participant in the room
        print("joining: room", self._room)
        self._cc.join(self._room.room_url, self._room.token, completion=self._on_joined)
        print("maybe joined")

    def _on_left(self, _, error):
        if error:
            raise Exception(f'Failed to leave room: {error}')
        self._done = True

    def _get_participant_count(self) -> int:
        r = self._room
        api_url = f'{r.api_url}rooms/{r.name}/presence'
        res = requests.get(
            api_url,
            headers={'Authorization': f'Bearer {self._api_key}'}
        )
        if not res.ok:
            raise Exception(f'Failed to get participant count: {res.status_code}, {res.text}')
        presence = res.json()
        count = int(presence['total_count'])
        print("returning count:", count)
        return count


    def _get_room(self, url: str, key: str) -> Room:
        u = urlparse(url)
        name = u.path.split('/')[1]
        subdomain = u.netloc.split('.')[1:]
        api_host = '.'.join(subdomain)

        r = Room(name,
                 url,
            f'https://api.{api_host}/v1/', '')
        
        r.token = self._get_meeting_token(r)
        return r

argparser = argparse.ArgumentParser()
argparser.add_argument('--url', help='Daily room URL to join')
argparser.add_argument('--key', help='Daily API key')
args = argparser.parse_args()

Daily.init()
c = Client(args.url, args.key)
c.join()
while not c.done:
    time.sleep(5)
Daily.deinit()