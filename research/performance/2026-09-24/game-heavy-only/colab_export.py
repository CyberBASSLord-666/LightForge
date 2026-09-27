HG_archive_path = HG_RUN.with_suffix(".zip")
assert not HG_archive_path.exists(), "Refusing to overwrite evidence archive."
with zipfile.ZipFile(HG_archive_path, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=1) as archive:
    for path in sorted(HG_RUN.rglob("*")):
        if path.is_file() and not path.is_symlink():
            archive.write(path, arcname=str(path.relative_to(HG_RUN.parent)))
print("Evidence:", HG_archive_path.name, "bytes:", HG_archive_path.stat().st_size)
print("SHA-256:", digest(HG_archive_path))
from google.colab import files
files.download(str(HG_archive_path))
