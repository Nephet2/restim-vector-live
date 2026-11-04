import asyncio,unittest
from unittest.mock import patch
from vector1a.civet import Civet,decode_pressure

class CivetDependencyTests(unittest.TestCase):
 def test_bundled_backend_imports_without_scanning(self):
  from bleak import BleakClient,BleakScanner
  from bleak.backends.winrt.client import BleakClientWinRT
  from bleak.backends.winrt.scanner import BleakScannerWinRT
  self.assertTrue(callable(BleakClient));self.assertTrue(callable(BleakScanner))

 def test_missing_dependency_explains_candidate_runtime(self):
  original=__import__
  def import_module(name,*args,**kwargs):
   if name=='bleak':raise ModuleNotFoundError('No module named bleak')
   return original(name,*args,**kwargs)
  with patch('builtins.__import__',side_effect=import_module):
   with self.assertRaisesRegex(RuntimeError,'Python 3.13 x64'):asyncio.run(Civet()._run())

 def test_pressure_decoder_unchanged(self):
  packet=bytearray(17);packet[0]=0xd0;packet[8:10]=(2134).to_bytes(2,'little',signed=True)
  self.assertEqual(decode_pressure(packet),21.34)

if __name__=='__main__':unittest.main()
