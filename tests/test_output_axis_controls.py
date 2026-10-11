import itertools
import unittest
from vector1a.network import ReStimWebSocketClient


def decode(frame):
    size, index = frame[1] & 127, 2
    if size == 126:
        size, index = int.from_bytes(frame[2:4], 'big'), 4
    mask, payload = frame[index:index+4], frame[index+4:index+4+size]
    return bytes(value ^ mask[i % 4] for i, value in enumerate(payload)).decode()


class OutputAxisControlTests(unittest.TestCase):
    def client(self):
        messages = []
        client = ReStimWebSocketClient(lambda _: None)
        client._socket = type('Socket', (), {'sendall': lambda _, frame: messages.append(decode(frame))})()
        return client, messages

    def test_all_checkbox_combinations_and_authored_overrides(self):
        axes = ('C0', 'P0', 'P3', 'P1')
        for flags in itertools.product((False, True), repeat=4):
            client, messages = self.client()
            client.suppressed_axes = frozenset(a for a, flag in zip(axes, flags) if not flag)
            client.send_primary(.1, .2, (1, .5, .5, .5), .3, .4, .5, .6, .7,
                                overrides={a: .9 for a in axes})
            tokens = {t[:2] for t in messages[-1].split()}
            for axis, enabled in zip(axes, flags):
                self.assertEqual(axis in tokens, enabled)
            self.assertTrue({'L0', 'L1', 'E1', 'E2', 'E3', 'E4', 'V0'} <= tokens)

    def test_secondary_and_reconnect_neutral(self):
        client, messages = self.client()
        client.suppressed_axes = frozenset(('F0', 'P0', 'P1', 'P3'))
        client._needs_neutral = True
        client.send_prostate(.1, .2, .3, .4, .5, .6, .7)
        self.assertEqual(len(messages), 2)
        self.assertEqual({t[:2] for t in messages[0].split()}, {'L0', 'L1', 'V0'})
        self.assertEqual({t[:2] for t in messages[1].split()}, {'L0', 'L1', 'V0'})

    def test_reenable_resumes_transmission(self):
        client, messages = self.client()
        client.suppressed_axes = frozenset(('C0',))
        client.send_four_phase((1, .5, .5, .5), frequency=.3)
        self.assertNotIn('C0', messages[-1])
        client.suppressed_axes = frozenset()
        client.send_four_phase((1, .5, .5, .5), frequency=.3)
        self.assertIn('C03000', messages[-1])
