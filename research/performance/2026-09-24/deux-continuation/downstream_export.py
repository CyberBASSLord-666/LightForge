# Download only the completed immutable archive created by deux_downstream.py.
import hashlib as DS_export_hashlib
from pathlib import Path as DS_export_Path
assert DS_archive_path.is_file() and not DS_archive_path.is_symlink()
with DS_archive_path.open("rb") as DS_export_stream:
    assert DS_export_hashlib.file_digest(DS_export_stream, "sha256").hexdigest() == DS_archive_sha256
print("Evidence:", DS_archive_path.name, "bytes:", DS_archive_path.stat().st_size)
print("SHA-256:", DS_archive_sha256)
try:
    from google.colab import files as DS_colab_files
except ImportError:
    from IPython.display import FileLink as DS_FileLink, display as DS_display
    DS_display(DS_FileLink(str(DS_archive_path)))
else:
    DS_colab_files.download(str(DS_archive_path))
