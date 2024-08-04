import os
import shutil
from collections import defaultdict
from sys import argv
import re
import requests
from dataclasses import dataclass
from OSAgnostics import (
    DirEntry,
    RENAME,
    PATH_SEP,
    OMDB_URL,
    OMDB_APIKEY,
)


@dataclass
class Episode:
    title: str = None
    season_id: int = None
    episode_from_id: int = None
    episode_to_id: int = None
    part_no: int = None
    extension: str = None


class Series:

    SERIES_COMPLIANT: re.Pattern = re.compile(r'^(.+) \((\d{4}(\-(\d{4})?)?)\) \[imdbid-(tt\d+)\]$', flags=re.IGNORECASE)
    SEASON_COMPLIANT: re.Pattern = re.compile(r'^Season (\d{2})$', flags=re.IGNORECASE)
    EPISODE_COMPLIANT: re.Pattern = re.compile(
        pattern=r'^(.+) S(\d+)E(\d+)(-E(\d+))?( Part (\d+))?\.(mkv|mp4|avi|ts|wmv)$',
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
        self._episodes: dict[str, Episode] = None
        self._decompose()

    def _decompose(self) -> None:
        match: re.Match = Series.SERIES_COMPLIANT.fullmatch(self._name)
        if match:
            groups = match.groups()
            self._title = groups[0]
            self._year = groups[1]
            self._imdbid = groups[4]
        else:
            match = re.search(r'\[imdbid-(tt\d+)\]', self._name)
            if match:
                self._imdbid = match.groups()[0]
                self._need_fix = True
            else:
                self._imdbid = None
                self._need_fix = False
                print('!!! Please include [imdbid-ttXXXXXX] in the movie folder name.')
        episodes: dict[str, Episode] = {}
        f_entries: list[DirEntry] = [
            i for i in os.scandir(self._path)
            if i.is_file() and re.match(r'^.*\.(mkv|mp4|avi|ts|wmv)$', i.name, flags=re.IGNORECASE)
        ]
        if len(f_entries) > 0:
            self._need_fix = True
            for f_entry in f_entries:
                episode: Episode = Episode()
                match = Series.EPISODE_COMPLIANT.fullmatch(f_entry.name)
                if match:
                    groups = match.groups()
                    episode.title = groups[0]
                    episode.season_id = int(groups[1])
                    episode.episode_from_id = int(groups[2])
                    episode.episode_to_id = int(groups[4]) if groups[3] else None
                    episode.part_no = int(groups[6]) if groups[5] else None
                    episode.extension = groups[7]
                else:
                    match = re.search(r'S(\d+)E(\d+)(-E(\d+))?', f_entry.name, flags=re.IGNORECASE)
                    if match:
                        groups = match.groups()
                        episode.season_id = int(groups[0])
                        episode.episode_from_id = int(groups[1])
                        episode.episode_to_id = int(groups[3]) if groups[2] else None
                    episode.extension = f_entry.name.split(sep='.')[-1]
                    match = re.search(r'(part|cd|disc)[ \-_]*(\d+)', f_entry.name, flags=re.IGNORECASE)
                    if match:
                        episode.part_no = int(match.groups()[1])
                episodes[f_entry.name] = episode
        d_entries: list[DirEntry] = [
            i for i in os.scandir(self._path)
            if i.is_dir() and re.match(r'^Season \d+$', i.name, flags=re.IGNORECASE)
        ]
        if len(d_entries) > 0:
            for d_entry in d_entries:
                self._need_fix = self._need_fix or not Series.SEASON_COMPLIANT.fullmatch(d_entry.name)
                this_season_id: int = int(re.match(r'^Season (\d+)$', d_entry.name, flags=re.IGNORECASE).groups()[0])
                f_entries = [
                    i for i in os.scandir(d_entry.path)
                    if i.is_file() and re.match(r'^.*\.(mkv|mp4|avi|ts|wmv)$', i.name, flags=re.IGNORECASE)
                ]
                for f_entry in f_entries:
                    episode: Episode = Episode()
                    match = Series.EPISODE_COMPLIANT.fullmatch(f_entry.name)
                    if match:
                        groups = match.groups()
                        episode.title = groups[0]
                        episode.season_id = int(groups[1])
                        episode.episode_from_id = int(groups[2])
                        episode.episode_to_id = int(groups[4]) if groups[3] else None
                        episode.part_no = int(groups[6]) if groups[5] else None
                        episode.extension = groups[7]
                    else:
                        self._need_fix = True
                        match = re.search(r'(S(\d+))?E(\d+)(-E(\d+))?', f_entry.name, flags=re.IGNORECASE)
                        if match:
                            groups = match.groups()
                            episode.season_id = int(groups[1]) if groups[0] else this_season_id
                            episode.episode_from_id = int(groups[2])
                            episode.episode_to_id = int(groups[4]) if groups[3] else None
                        episode.extension = f_entry.name.split(sep='.')[-1]
                        match = re.search(r'(part|cd|disc)[ \-_]*(\d+)', f_entry.name, flags=re.IGNORECASE)
                        if match:
                            episode.part_no = int(match.groups()[1])
                    episodes[f'{d_entry.name}{PATH_SEP}{f_entry.name}'] = episode

        self._episodes = episodes

    def need_fix(self) -> bool:
        if not self._need_fix:
            self._need_fix = self._need_fix or self._title is None or self._year is None
        if not self._need_fix:
            for episode in self._episodes.values():
                self._need_fix = self._need_fix or self._title != episode.title
        self._need_fix = self._need_fix and self._imdbid

        return self._need_fix

    def fix(self, dry_run: bool = False) -> None:
        if not self._imdbid:
            print(f"--- cannot fix without a known imdbid")
            return
        if not self.need_fix():
            print(f"--- no need to fix as it's already compliant")
            return
        (self._title, self._year, _) = Series.get_omdb_series(self._imdbid)
        # rename the episodes first
        season_ids: set[int] = set(i.season_id for i in self._episodes.values())
        for s_id in season_ids:
            mkdir = f'{self._path}{PATH_SEP}Season {s_id:02d}'
            print(f"+++ mkdir <{mkdir}>")
            if not dry_run:
                os.makedirs(mkdir, exist_ok=True)
        rename_episodes: dict[str, str] = {}
        for old_name, episode in self._episodes.items():
            episode.title = self._title
            new_name: str = f"Season {episode.season_id:02d}{PATH_SEP}{episode.title} S{episode.season_id:02d}E{episode.episode_from_id:02d}"
            if episode.episode_to_id:
                new_name += f"-E{episode.episode_to_id:02d}"
            if episode.part_no:
                new_name += f" Part {episode.part_no}"
            new_name += f".{episode.extension}"
            rename_episodes[old_name] = new_name
        if len(rename_episodes) > len(set(rename_episodes.values())):
            print(f"--- cannot fix as 2 or more episodes are identical")
            return
        for old, new in rename_episodes.items():
            if old != new:
                print(f"+++ <{old}> ==> <{new}>")
                if not dry_run:
                    shutil.move(f"{self._path}{PATH_SEP}{old}", f"{self._path}{PATH_SEP}{new}")
                    self._episodes[new] = self._episodes.pop(old)
            else:
                print(f"--- no change for identical old/new episodes <{old}>")

        # then rename the series
        new_series_name: str = f"{self._title} ({self._year}) [imdbid-{self._imdbid}]"
        if self._name != new_series_name:
            print(f"+++ <{self._name}> ==> <{new_series_name}>")
            if not dry_run:
                shutil.move(self._path, f"{self._parent}{PATH_SEP}{new_series_name}")
                self._name = new_series_name
                self._path = f"{self._parent}{PATH_SEP}{new_series_name}"
                self._need_fix = False
        else:
            print(f"--- no change for identical series <{self._name}>")

        return

    def dry_run(self) -> None:
        self.fix(dry_run=True)

    def __str__(self) -> str:
        return (f"Series(title={self._title}, year={self._year}, imdbid={self._imdbid}, "
                f"episodes={list(self._episodes.values())}, path={self._path})")

    # @staticmethod
    # def parse_path(path_str: str) -> tuple[str]:
    #     title, year, imdbid = None, None, None
    #     ascii_tail: re.Match = re.search(r"([ -~]+)$", path_str)
    #     ascii_path: str = ascii_tail.groups()[0] if ascii_tail else None
    #     if ascii_path:
    #         right: int = len(ascii_path)
    #         imdbid: re.Match = re.search(r"imdbid-(tt\d+)", ascii_path[:right])
    #         right = imdbid.start() if imdbid else right
    #         variant: re.Match = re.search(r"\d{3,4}[pPiI]", ascii_path[:right])
    #         right = variant.start() if variant else right
    #         year: re.Match = re.search(r".+[ \.\(\)_\[\]]+(\d{4})", ascii_path[:right])
    #         right = (year.end() - 4) if year else right
    #         title: list[str] = re.split(r"[ \.\(\)_\[\]]+", ascii_path[:right])
    #         title = " ".join(title).strip().title()
    #         year = year.groups()[0] if year else None
    #         imdbid = imdbid.groups()[0] if imdbid else None

    #     return (title, year, imdbid)

    @staticmethod
    def get_omdb_series(imdbid: str) -> tuple[str | None]:
        title, year = None, None
        if imdbid:
            query_params: dict[str, str] = {
                "apikey": OMDB_APIKEY,
                "i": imdbid,
                "type": "series",
                "r": "json",
            }
            resp: requests.Response = requests.get(OMDB_URL, params=query_params)
            if resp.status_code // 100 == 2:
                result: dict = resp.json()
                if result["Response"] == "True":
                    good_title: str = re.sub(r"[ /\\:\*<>\|\?]+", " ", result["Title"])
                    good_year: str = re.sub(r'[^ -~]+', '-', result["Year"])
                    (title, year, imdbid) = (
                        good_title,
                        good_year,
                        result["imdbID"]
                    )
            elif resp.status_code // 100 == 4:
                result: dict = resp.json()
                if result["Error"] == "Request limit reached!":
                    raise Exception(
                        f'!!! Reached daily limit when retrieve details for "{imdbid}"'
                    )

        return (title, year, imdbid)

    # @staticmethod
    # def search_omdb(title: str, year: str) -> tuple[str | None]:
    #     imdbid: str = None
    #     if title:
    #         query_params: dict[str, str] = {
    #             "apikey": OMDB_APIKEY,
    #             "s": title,
    #             "type": "series",
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
    #                     good_title: str = re.sub(
    #                         r"[ /\\:\*<>\|\?]+", " ", entry["Title"]
    #                     )
    #                     (title, year, imdbid) = (
    #                         good_title,
    #                         entry["Year"],
    #                         entry["imdbID"]
    #                     )
    #         elif resp.status_code // 100 == 4:
    #             result: dict = resp.json()
    #             if result["Error"] == "Request limit reached!":
    #                 raise Exception(
    #                     f'!!! Reached daily limit when search for "{title} ({year})"'
    #                 )

    #     return (title, year, imdbid)

    # @staticmethod
    # def get_episodes(
    #     folder_path: str,
    #     pattern: str = r"^.*\.(mkv|mp4|ts|avi|wmv)$"
    # ) -> dict[str, tuple[int]]:
    #     entries: list[DirEntry] = [i for i in os.scandir(folder_path) if i.is_file()]
    #     dirs: list[DirEntry] = [i.path for i in os.scandir(folder_path) if i.is_dir()]
    #     for dir in dirs:
    #         entries.extend([i for i in os.scandir(dir) if i.is_file()])
    #     if pattern:
    #         entries = [
    #             i for i in entries if re.match(pattern, i.name, flags=re.IGNORECASE)
    #         ]
    #     episodes: dict[str, tuple[int]] = dict()
    #     for entry in entries:
    #         season, episode = (None, None)
    #         found: re.Match = re.search(r"s(\d+)\.?e(\d+)", entry.name, flags=re.IGNORECASE)
    #         if found:
    #             season, episode = found.groups()
    #         if not episode:
    #             found = re.search(r"(episode|ep|e|part)[\-\. ]?(\d+)", entry.name, flags=re.IGNORECASE)
    #             if found:
    #                 episode = found.groups()[1]
    #         if not episode:
    #             found = re.search(r"(\d+)of(\d+)", entry.name, flags=re.IGNORECASE)
    #             if found:
    #                 episode = found.groups()[0]
    #         if not episode:
    #             found = re.search(r"(\d+)x(\d+)", entry.name, flags=re.IGNORECASE)
    #             if found:
    #                 season, episode = found.groups()
    #         if not episode:
    #             found = re.search(r"[^p](\d+)", entry.name, flags=re.IGNORECASE)
    #             if found:
    #                 episode = found.groups()[0]
    #         if not season:
    #             found = re.search(r"(season|series)[\-\. ]?(\d+)", entry.path, flags=re.IGNORECASE)
    #             season = found.groups()[1] if found else '1'

    #         if season and episode:
    #             episodes[entry.path] = (int(season), int(episode))

    #     return episodes


if __name__ == "__main__":
    series_path: str = argv[1]
    print(f"??? {series_path=}")
    series: Series = Series(series_path)
    print(series)
    # series.dry_run()
    series.fix()
