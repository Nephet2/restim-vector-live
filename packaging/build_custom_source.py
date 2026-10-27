"""Build the public source ZIP from tracked files and a verified Pillow wheel."""
from __future__ import annotations
import argparse
import ast
import hashlib
from pathlib import Path
import subprocess
import zipfile

PILLOW_SHA256 = '4cf7fed4b4580601c4345ceb5d4cbf5a980d030fd5ad07c4d2ec589f95f09905'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--pillow-wheel', type=Path, required=True)
    parser.add_argument('--output', type=Path, default=Path('dist'))
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    wheel = args.pillow_wheel.resolve()
    if hashlib.sha256(wheel.read_bytes()).hexdigest() != PILLOW_SHA256:
        raise SystemExit('Pillow wheel does not match the verified publisher hash')
    version = next(node.value.value for node in ast.parse((root/'vector1a/__init__.py').read_text()).body
                   if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id=='__version__' for t in node.targets))
    prefix = 'Vector1A-' + version
    out = args.output.resolve();out.mkdir(parents=True, exist_ok=True)
    archive = out / (prefix + '-source-windows.zip')
    files = subprocess.check_output(['git','ls-files','-z'], cwd=root).decode('utf-8').split('\0')
    entries = {}
    for name in filter(None, files):
        path = Path(name)
        if path.is_absolute() or '..' in path.parts or any(part in {'profile','backups','__pycache__'} for part in path.parts):
            raise SystemExit('Private or unexpected tracked path: ' + name)
        if path.suffix.lower() in {'.exe','.pyc','.pyd','.dll'} or path.name in {'settings.json','civet-pressure.json'}:
            raise SystemExit('Unexpected tracked runtime/settings file: ' + name)
        data=(root/path).read_bytes()
        try:data=data.decode('utf-8').replace('\r\n','\n').encode('utf-8')
        except UnicodeDecodeError:pass
        entries[prefix+'/'+path.as_posix()]=data
    with zipfile.ZipFile(wheel) as source:
        for name in source.namelist():
            if name.endswith('/'):continue
            if Path(name).is_absolute() or '..' in Path(name).parts:
                raise SystemExit('Unexpected wheel path')
            entries[prefix+'/dependencies/'+name]=source.read(name)
    with zipfile.ZipFile(archive,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=9) as dest:
        for name,data in sorted(entries.items()):
            info=zipfile.ZipInfo(name,date_time=(2026,10,27,0,0,0))
            info.compress_type=zipfile.ZIP_DEFLATED;info.external_attr=0o100644 << 16
            dest.writestr(info,data,compresslevel=9)
    with zipfile.ZipFile(archive) as check:
        if check.testzip() is not None:raise SystemExit('Archive integrity check failed')
        required=[prefix+'/'+name for name in ['start-vector1a.bat','standalone_entry.py','vector1a/connection_actions.py']]
        if not all(name in check.namelist() for name in required):raise SystemExit('Missing startup source')
    digest=hashlib.sha256(archive.read_bytes()).hexdigest()
    Path(str(archive)+'.sha256').write_text(digest+'  '+archive.name+'\n',encoding='ascii')
    print(str(archive));print('SHA-256: '+digest)


if __name__=='__main__':main()
