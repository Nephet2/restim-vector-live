"""Verify public archives contain application data and no private profiles."""
from pathlib import Path, PurePosixPath
from zipfile import ZipFile

for path in Path("dist").glob("*.zip"):
    with ZipFile(path) as archive:
        names = archive.namelist()
        assert names, f"Empty archive: {path}"
        for name in names:
            parts = PurePosixPath(name.replace("\\", "/")).parts
            assert not {"profile", "backups", "__pycache__"} & set(parts), name
            assert parts[-1] not in {"settings.json", "civet-pressure.json"}, name
        assert any(n.endswith("event_definitions.yml") for n in names), path
        assert any(n.endswith("THIRD_PARTY_NOTICES.md") for n in names), path
        if path.name.endswith("-exe.zip"):
            assert any(n.endswith(".exe") for n in names), path
            assert any("/_internal/" in n.replace("\\", "/") for n in names), path
    print(f"Verified {path.name}: {len(names)} entries")
