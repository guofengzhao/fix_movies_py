import os
import re
import json
import argparse
from datetime import datetime, timedelta, UTC
from movie import Movie
from concurrent import futures

if os.name == "posix":
    from posix import DirEntry
else:
    from nt import DirEntry


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--basedir", required=True, dest="basedir")
    parser.add_argument("--dryrun", dest="dryrun", action="store_true")
    args = parser.parse_args()
    return args


def get_subdirs(basedir: str, filter: str = None) -> list[DirEntry]:
    entries: list[DirEntry] = []
    with os.scandir(basedir) as nodes:
        for entry in nodes:
            if entry.is_dir:
                entries.append(entry)
    if filter:
        entries = [i for i in entries if re.match(filter, i.name)]

    return entries


def process_subdir(subdir: str, dryrun: bool) -> bool:
    print(f"??? {subdir}")
    try:
        movie: Movie = Movie(subdir)
        movie.fix(dry_run=dryrun)
    except Exception as ex:
        print(f'Error in processing <{subdir}>: {str(ex)}')
        return False

    return True


def main():
    args = parse_args()
    basedir: str = args.basedir
    dryrun: bool = args.dryrun
    print(f"=== {basedir=} {dryrun=} ===")
    movie_dirs: list[DirEntry] = get_subdirs(basedir)
    result: int = 0
    start_time: datetime = datetime.now(UTC)

    # looping
    # print(f'looping started at {start_time.isoformat()}')
    # for movie_dir in movie_dirs:
    #     ok: bool = process_subdir(movie_dir.path, dryrun)
    #     result += (1 if ok else 0)
    # finish_time: datetime = datetime.now(UTC)
    # print(f'looping finished at {finish_time.isoformat()}')
    # time_used: timedelta = finish_time - start_time
    # print(f'looping duration: {time_used}, total movies: {result}')

    # futrues
    print(f'futures started at {start_time.isoformat()}')
    with futures.ProcessPoolExecutor(max_workers=10) as pool:
        tasks: list[futures.Future] = [
            pool.submit(process_subdir, movie_dir.path, dryrun)
            for movie_dir in movie_dirs
        ]
    for completed in futures.as_completed(tasks):
        result += (1 if completed.result() else 0)
    finish_time: datetime = datetime.now(UTC)
    print(f'futures finished at {finish_time.isoformat()}')
    time_used: timedelta = finish_time - start_time
    print(f'futures duration: {time_used}, total movies: {result}')

if __name__ == "__main__":
    main()
