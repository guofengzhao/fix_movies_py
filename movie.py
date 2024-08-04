import os
import shutil
import subprocess
from sys import argv
import re
import json
from dataclasses import dataclass
# from xmlrpc.client import boolean
import requests
from OSAgnostics import (
    DirEntry,
    EXIFTOOL,
    PATH_SEP,
    EXIFTOOL_OPTS,
    OMDB_URL,
    OMDB_APIKEY,
    RESOLUTIONS,
    RESOLUTIONS_STR,
)


@dataclass
class Medium:
    title: str = None
    year: str = None
    resolution: str = None
    extension: str = None
    part_no: int = None
    is_3d: bool = False
    d3_format: str = None

class Movie:

    MOVIE_COMPLIANT: re.Pattern = re.compile(r'^(.+) \(((19|20)\d{2})\) \[imdbid-(tt\d+)\]$', flags=re.IGNORECASE)
    MEDIUM_COMPLIANT: re.Pattern = re.compile(
        # r'^(.+) \(((19|20)\d{2})\) (\[3D\.(FTAB|HSBS|FSBS)\] )?(\[Part (\d+)\] )?- \[(\d{3,4}(p|i))\]\.(mkv|mp4|avi|ts|wmv)$',
        pattern=(
            r'^(.+) \(((19|20)\d{2})\) (\[3D\.(FTAB|HSBS|FSBS)\] )?(\[Part (\d+)\] )?- \[(('
            + RESOLUTIONS_STR
            + r')(p|i))\]\.(mkv|mp4|avi|ts|wmv)$'),
        flags=re.IGNORECASE
    )
    def __init__(self, path: str) -> None:
        self._path: str = path
        self._name: str = path.split(sep=PATH_SEP)[-1]
        self._parent: str = PATH_SEP.join(path.split(sep=PATH_SEP)[:-1])
        self._title: str = None
        self._year: str = None
        self._imdbid: str = None
        self._need_fix: bool = False
        self._media: dict[str, Medium] = None
        self._decompose()

    def _decompose(self) -> None:
        match: re.Match = Movie.MOVIE_COMPLIANT.fullmatch(self._name)
        if match:
            groups = match.groups()
            self._title = groups[0]
            self._year = groups[1]
            self._imdbid = groups[3]
        else:
            match = re.search(r'\[imdbid-(tt\d+)\]', self._name)
            if match:
                self._imdbid = match.groups()[0]
                self._need_fix = True
            else:
                self._imdbid = None
                self._need_fix = False
                print('!!! Please include [imdbid-ttXXXXXX] in the movie folder name.')

        entries: list[DirEntry] = [i for i in os.scandir(self._path) if i.is_file()]
        entries = [
            i for i in entries if re.match(r'^.*\.(mkv|mp4|avi|ts|wmv)$', i.name, flags=re.IGNORECASE)
        ]
        if len(entries) > 0:
            media: dict[str, Medium] = {}
            for entry in entries:
                medium: Medium = Medium()
                match = Movie.MEDIUM_COMPLIANT.fullmatch(entry.name)
                if match:
                    groups = match.groups()
                    medium.title = groups[0]
                    medium.year = groups[1]
                    medium.is_3d = groups[3] is not None
                    medium.d3_format = groups[4] if medium.is_3d else medium.d3_format
                    medium.part_no = int(groups[6]) if groups[5] else None
                    medium.resolution = groups[7]
                    medium.extension = groups[10]
                else:
                    medium.resolution = Movie.get_resolution(entry.path)
                    match = re.search(r'(ftab|hsbs|fsbs)', entry.name, flags=re.IGNORECASE)
                    if match:
                        medium.is_3d = True
                        medium.d3_format = match.groups()[0].upper()
                    medium.extension = entry.name.split(sep='.')[-1]
                    match = re.search(r'(part|cd|disc)[ \-_]*(\d+)', entry.name, flags=re.IGNORECASE)
                    if match:
                        medium.part_no = int(match.groups()[1])
                    self._need_fix = True
                media[entry.name] = medium
            self._media = media

        return

    def need_fix(self) -> bool:
        if not self._need_fix:
            self._need_fix = self._need_fix or self._title is None or self._year is None
        if not self._need_fix:
            for medium in self._media.values():
                self._need_fix = self._need_fix or self._title != medium.title or self._year != medium.year
        self._need_fix = self._need_fix and self._imdbid

        return self._need_fix

    def fix(self, dry_run: bool = False) -> None:
        if not self._imdbid:
            print(f"--- cannot fix without a known imdbid")
            return
        if not self.need_fix():
            print(f"--- no need to fix as it's already compliant")
            return
        (self._title, self._year, _) = Movie.get_omdb_details(self._imdbid)
        # rename the media first
        rename_media: dict[str, str] = {}
        for name, medium in self._media.items():
            medium.title = self._title
            medium.year = self._year
            new_name: str = f"{medium.title} ({medium.year}) "
            if medium.is_3d:
                new_name += f"[3D.{medium.d3_format.upper()}] "
            if medium.part_no:
                new_name += f"[Part {medium.part_no}] "
            new_name += f"- [{medium.resolution}].{medium.extension}"
            rename_media[name] = new_name
        if len(rename_media) > len(set(rename_media.values())):
            print(f"--- cannot fix as 2 or more media are identical")
            return
        for old, new in rename_media.items():
            if old != new:
                print(f"+++ <{old}> ==> <{new}>")
                if not dry_run:
                    shutil.move(f"{self._path}{PATH_SEP}{old}", f"{self._path}{PATH_SEP}{new}")
                    self._media[new] = self._media.pop(old)
            else:
                print(f"--- no change for identical old/new media <{old}>")
        # then rename the movie
        new_movie_name: str = f"{self._title} ({self._year}) [imdbid-{self._imdbid}]"
        if self._name != new_movie_name:
            print(f"+++ <{self._name}> ==> <{new_movie_name}>")
            if not dry_run:
                shutil.move(self._path, f"{self._parent}{PATH_SEP}{new_movie_name}")
                self._name = new_movie_name
                self._path = f"{self._parent}{PATH_SEP}{new_movie_name}"
                self._need_fix = False
        else:
            print(f"--- no change for identical movie <{self._name}>")

        return

    def dry_run(self) -> None:
        self.fix(dry_run=True)

    def __str__(self) -> str:
        return f"Movie(title={self._title}, year={self._year}, imdbid={self._imdbid}, media={self._media}, path={self._path})"

    # def audit(self) -> bool:
    #     result: bool = Movie.is_movie_compliant(self._name)
    #     if self._media is None:
    #         self.media = Movie.get_media(self._path)
    #     for name in self._media:
    #         result &= Movie.is_medium_compliant(name)

    #     return result

    # @staticmethod
    # def parse_path(path_str: str) -> tuple[str]:
    #     title, year, imdbid = None, None, None
    #     ascii_path: re.Match = re.sub(r'[^ -~]+', ' ', path_str)
    #     if ascii_path:
    #         right: int = len(ascii_path)
    #         found: re.Match = re.search(r'imdbid-(tt\d+)', ascii_path[:right])
    #         if found:
    #             imdbid = found.groups()[0]
    #             right = found.start()
    #         found = re.search(r'\((19|20)(\d{2})\)', ascii_path[:right])
    #         if found:
    #             year = ''.join(found.groups())
    #             right = found.start()
    #         title: list[str] = re.split(r"[ \.\(\)_\[\]]+", ascii_path[:right])
    #         title = " ".join(title).strip().title()

    #     return (title, year, imdbid)

    @staticmethod
    def get_omdb_details(imdbid: str) -> tuple[str | None]:
        title, year = None, None
        if imdbid:
            query_params: dict[str, str] = {
                "apikey": OMDB_APIKEY,
                "i": imdbid,
                # "type": "movie",
                "r": "json",
            }
            resp: requests.Response = requests.get(OMDB_URL, params=query_params)
            if resp.status_code // 100 == 2:
                result: dict = resp.json()
                if result["Response"] == "True":
                    good_title: str = re.sub(r'[ /\\:\*<>\|\?]+', ' ', result["Title"])
                    (title, year, imdbid) = (
                        good_title,
                        result["Year"],
                        result["imdbID"],
                    )
            elif resp.status_code // 100 == 4:
                result: dict = resp.json()
                if result["Error"] == "Request limit reached!":
                    raise Exception(f'!!! Reached daily limit when retrieve details for "{imdbid}"')

        return (title, year, imdbid)

    # @staticmethod
    # def search_omdb(title: str, year: str) -> tuple[str | None]:
    #     imdbid: str = None
    #     if title:
    #         query_params: dict[str, str] = {
    #             "apikey": OMDB_APIKEY,
    #             "s": title,
    #             "type": "movie",
    #             "r": "json",
    #         }
    #         if year:
    #             query_params["y"] = year
    #         resp: requests.Response = requests.get(OMDB_URL, params=query_params)
    #         if resp.status_code // 100 == 2:
    #             result: dict = resp.json()
    #             if result["Response"] == "True":
    #                 if int(result["totalResults"]) > 0:
    #                     entry: dict = result["Search"][0]
    #                     good_title: str = re.sub(r"[ /\\:\*<>\|\?]+", " ", entry["Title"])
    #                     (title, year, imdbid) = (
    #                         good_title,
    #                         entry["Year"],
    #                         entry["imdbID"],
    #                     )
    #         elif resp.status_code // 100 == 4:
    #             result: dict = resp.json()
    #             if result["Error"] == "Request limit reached!":
    #                 raise Exception(f'!!! Reached daily limit when search for "{title} ({year})"')

    #     return (title, year, imdbid)

    # @staticmethod
    # def get_media(
    #     folder_path: str, pattern: str = r"^.*\.(mkv|mp4|avi|ts|wmv)$"
    # ) -> dict[str, Medium]:
    #     entries: list[DirEntry] = [i for i in os.scandir(folder_path) if i.is_file()]
    #     if pattern:
    #         entries = [
    #             i for i in entries if re.match(pattern, i.name, flags=re.IGNORECASE)
    #         ]
    #     media: dict[str, Medium] = dict()
    #     for file in entries:
    #         medium: Medium = Medium()
    #         found: re.Match = re.search(r'(part|cd|disc)[ \-_]*(\d+)', file.name, flags=re.IGNORECASE)
    #         if found:
    #             medium.part_no = int(found.groups()[1])
    #         medium.resolution = Movie.get_resolution(file.path)
    #         found = re.search(r'(ftab|hsbs|fsbs)|3d', file.name, flags=re.IGNORECASE)
    #         if found:
    #             medium.is_3d = True
    #             medium.d3_format = found.groups()[0].upper() if found.groups()[0] else 'HSBS'
    #         media[file.name] = medium

    #     return media

    @staticmethod
    def get_resolution(medium_path: str) -> str:
        proc = subprocess.Popen(
            args=[EXIFTOOL] + EXIFTOOL_OPTS + [medium_path],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        result, _ = proc.communicate()
        # result = result.split(sep=b'\r\n')
        # result = [i.decode('utf-8').strip().lower() for i in result]
        # meta_info = json.loads(result.decode('utf-8'))[0]
        meta_info = json.loads(result)[0]
        resolution: int = int(meta_info["Composite"]["ImageSize"].split(sep="x")[1])
        res: str = f"{min([i for i in RESOLUTIONS if i >= resolution])}p"

        return res

    # @staticmethod
    # def is_movie_compliant(name: str):
    #     match = Movie.MOVIE_COMPLIANT.fullmatch(name)

    #     return match is not None

    # @staticmethod
    # def is_medium_compliant(name: str):
    #     match = Movie.MEDIUM_COMPLIANT.fullmatch(name)

    #     return match is not None


if __name__ == "__main__":
    movie_path: str = argv[1]
    print(f"??? {movie_path=}")
    movie: Movie = Movie(movie_path)
    print(movie)
    movie.dry_run()
    # movie.fix()
