# Separate Colab export cell; usable after a completed or interrupted Deux attempt.
import hashlib as DX_export_hashlib
import zipfile as DX_export_zipfile
from pathlib import Path as DX_export_Path

assert DX_RUN.is_dir(), "Run the Deux continuation setup first."
DX_archive_path = DX_RUN.with_suffix(".zip")
assert not DX_archive_path.exists(), "Refusing to overwrite an earlier evidence archive."
with DX_export_zipfile.ZipFile(DX_archive_path, "x", compression=DX_export_zipfile.ZIP_DEFLATED, compresslevel=1) as DX_archive:
    for DX_path in sorted(DX_RUN.rglob("*")):
        assert not DX_path.is_symlink(), "Unexpected symlink in evidence: " + str(DX_path)
        if DX_path.is_file():
            DX_archive.write(DX_path, arcname=str(DX_path.relative_to(DX_RUN.parent)))
with DX_archive_path.open("rb") as DX_stream:
    DX_archive_sha256 = DX_export_hashlib.file_digest(DX_stream, "sha256").hexdigest()
print("Evidence:", DX_archive_path.name, "bytes:", DX_archive_path.stat().st_size)
print("SHA-256:", DX_archive_sha256)
try:
    from google.colab import files as DX_colab_files
except ImportError:
    from IPython.display import FileLink as DX_FileLink, display as DX_display
    DX_display(DX_FileLink(str(DX_archive_path)))
else:
    DX_colab_files.download(str(DX_archive_path))
