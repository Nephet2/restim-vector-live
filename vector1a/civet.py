"""DG Lab Civet telemetry. No device zeroing, rotation, or output commands."""
import asyncio
import struct
import threading
import time

SERVICE = '0000180c-0000-1000-8000-00805f9b34fb'
WRITE = '0000150a-0000-1000-8000-00805f9b34fb'
NOTIFY = '0000150b-0000-1000-8000-00805f9b34fb'
BATTERY = '00001500-0000-1000-8000-00805f9b34fb'
START = bytes([0x50, 0x01, 0xd0]) + bytes(14)
STOP = bytes([0x50, 0x01, 0x00]) + bytes(14)
STALE_SECONDS = 1.5


def decode_pressure(packet):
    # The vendor's conversion example uses zero-based byte offsets 8 and 9.
    if len(packet) != 17 or packet[0] != 0xd0:
        raise ValueError('Expected a 17-byte Civet D0 pressure packet')
    return struct.unpack_from('<h', packet, 8)[0] / 100.0


class Civet:
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.lock = threading.Lock()
        self.stop_event = threading.Event()
        self.thread = None
        self.status = 'Disconnected'
        self.connected = False
        self.value = None
        self.last_reading = None
        self.count = 0
        self.bad_packets = 0
        self.battery = None

    def snapshot(self):
        with self.lock:
            age = None if self.last_reading is None else max(0, self.clock() - self.last_reading)
            return {'status': self.status, 'connected': self.connected, 'pressure_kpa': self.value,
                    'age_seconds': age, 'fresh': self.connected and age is not None and age <= STALE_SECONDS,
                    'readings': self.count, 'bad_packets': self.bad_packets, 'battery': self.battery,
                    'busy': self.thread is not None and self.thread.is_alive()}

    def receive(self, sender, packet):
        try:
            value = decode_pressure(packet)
        except ValueError:
            with self.lock:
                self.bad_packets += 1
            return
        with self.lock:
            self.value = value
            self.last_reading = self.clock()
            self.count += 1

    def connect(self):
        if self.thread is not None and self.thread.is_alive():
            return
        self.stop_event.clear()
        with self.lock:
            self.connected = False
            self.value = self.last_reading = self.battery = None
            self.count = self.bad_packets = 0
            self.status = 'Searching for Civet…'
        self.thread = threading.Thread(target=self._worker, daemon=True)
        self.thread.start()

    def disconnect(self):
        # Immediately invalidate readings, even while Windows is still disconnecting.
        with self.lock:
            self.connected = False
            self.status = 'Disconnecting…'
        self.stop_event.set()

    def _worker(self):
        try:
            asyncio.run(self._run())
        except Exception as exc:
            with self.lock:
                self.status = 'Connection failed: ' + str(exc)
        finally:
            with self.lock:
                self.connected = False
                if self.stop_event.is_set():
                    self.status = 'Disconnected'

    async def _run(self):
        from bleak import BleakScanner, BleakClient
        found = await BleakScanner.discover(timeout=6, return_adv=True)
        if self.stop_event.is_set():
            return
        matches = [device for device, ad in found.values()
                   if (ad.local_name or device.name or '') == '47L124000']
        if len(matches) != 1:
            raise RuntimeError('No Civet found. Make its Bluetooth icon yellow and retry.' if not matches
                               else 'Multiple Civets found. Switch off the others and retry.')
        with self.lock:
            self.status = 'Connecting to Civet…'
        def lost(client):
            with self.lock:
                self.connected = False
                self.status = 'Civet disconnected. Make it discoverable and reconnect.'
        async with BleakClient(matches[0], timeout=15, disconnected_callback=lost) as client:
            if self.stop_event.is_set():
                return
            service = client.services.get_service(SERVICE)
            write = service.get_characteristic(WRITE) if service else None
            notify = service.get_characteristic(NOTIFY) if service else None
            if write is None or notify is None:
                raise RuntimeError('The device does not expose the expected Civet pressure service.')
            response = 'write' in write.properties
            await client.start_notify(notify, self.receive)
            try:
                await client.write_gatt_char(write, START, response=response)
                with self.lock:
                    if not self.stop_event.is_set():
                        self.connected = True
                        self.status = 'Connected · waiting for pressure' if self.value is None else 'Connected'
                try:
                    battery = await asyncio.wait_for(client.read_gatt_char(BATTERY), timeout=2)
                    with self.lock:
                        self.battery = battery[0] if len(battery) == 1 and battery[0] <= 100 else None
                except Exception:
                    pass  # Battery telemetry is optional, pressure is not.
                while not self.stop_event.is_set() and client.is_connected:
                    with self.lock:
                        if self.value is not None:
                            self.status = 'Connected'
                    await asyncio.sleep(.1)
            finally:
                if client.is_connected:
                    try:
                        await asyncio.wait_for(client.write_gatt_char(write, STOP, response=response), timeout=2)
                    except Exception:
                        pass
