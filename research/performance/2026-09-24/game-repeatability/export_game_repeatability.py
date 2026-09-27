assert REP_process.poll() is not None, "Stop the active screen before exporting its evidence."
try:
    os.killpg(REP_process.pid,0)
except ProcessLookupError:
    pass
else:
    raise RuntimeError("A screen process-group member remains; preserve evidence and finish cleanup before export.")
REP_archive = REP_RUN.with_suffix(".zip")
assert not REP_archive.exists(), "Refusing to overwrite repeatability evidence."
with zipfile.ZipFile(REP_archive,"x",compression=zipfile.ZIP_DEFLATED,compresslevel=1) as REP_zip:
    for REP_path in sorted(REP_RUN.rglob("*")):
        if REP_path.is_file() and not REP_path.is_symlink():
            REP_zip.write(REP_path,arcname=str(REP_path.relative_to(REP_RUN.parent)))
print("Evidence:",REP_archive.name,"bytes:",REP_archive.stat().st_size)
print("SHA-256:",digest(REP_archive))
from google.colab import files
files.download(str(REP_archive))
