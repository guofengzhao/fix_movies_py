import os

if os.name == "posix":
    from posix import DirEntry

    RENAME: str = "mv"
    Q: str = "'"
    EXIFTOOL = "/usr/bin/exiftool"
else:
    from nt import DirEntry

    RENAME: str = "move"
    Q: str = '"'
    EXIFTOOL = "exiftool.exe"

PATH_SEP: str = os.path.sep
EXIFTOOL_OPTS = ["-json", "-g1"]
OMDB_URL: str = "http://www.omdbapi.com/"
OMDB_APIKEY: str = os.environ.get('OMDB_APIKEY')

RESOLUTIONS = [360, 480, 720, 1080, 2160]

RESOLUTIONS_STR = '|'.join([str(i) for i in RESOLUTIONS])