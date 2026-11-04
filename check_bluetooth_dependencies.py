"""Import-only check; never starts Bluetooth discovery or connects hardware."""
from pathlib import Path
import sys
import platform
if sys.version_info[:2] != (3,13) or platform.machine().lower() not in ('amd64','x86_64'):
    raise SystemExit('Bundled Bluetooth backend requires Python 3.13 x64. No scan started.')
sys.path.insert(0, str(Path(__file__).resolve().parent))
import standalone_entry
from bleak import BleakClient,BleakScanner
from bleak.backends.winrt.client import BleakClientWinRT
from bleak.backends.winrt.scanner import BleakScannerWinRT
print('Civet Bluetooth dependencies load successfully. No scan or device connection started.')
