DT_archive_path = DT_RUN.with_suffix(".zip")
assert not DT_archive_path.exists(), "Refusing to overwrite evidence archive."
with zipfile.ZipFile(DT_archive_path, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=1) as archive:
    for path in sorted(DT_RUN.rglob("*")):
        if path.is_file() and not path.is_symlink():
            archive.write(path, arcname=str(path.relative_to(DT_RUN.parent)))
print("Evidence:", DT_archive_path.name, "bytes:", DT_archive_path.stat().st_size)
print("SHA-256:", digest(DT_archive_path))
from google.colab import files
files.download(str(DT_archive_path))
