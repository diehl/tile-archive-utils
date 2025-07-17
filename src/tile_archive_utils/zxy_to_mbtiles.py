#!/usr/bin/env python3
"""
ZXY to MBTiles Converter

This script converts a ZXY directory of tiles into an MBTiles archive.
"""

import os
import sys
import time
import click
import sqlite3

from tqdm import tqdm
from pathlib import Path
from typing import Tuple
from datetime import timedelta


class MBTilesConstructor:
    """Constructs an MBTiles archive from a ZXY directory of tiles"""

    def __init__(self, zxy_dir: str, mbtiles_path: str,
                 tile_format: str, batch_size: int,
                 name: str = None, description: str = None) -> None:
        """Initialize a new MBTilesConstructor instance

           Arguments:
           zxy_dir (str):                  path to the ZXY directory structure
           mbtiles_path (str):             path to the resulting MBTiles file
           tile_format (str):              tile format (png, jpg, webp, etc)
           batch_size (int):               tile batch size for database inserts
           name (optional[str]):           tileset name. defaults to None.
           description (optional[str]):    tileset description. defaults to
                                           None.
        """
        self.zxy_dir = Path(zxy_dir)
        self.mbtiles_path = mbtiles_path
        self.tile_format = tile_format
        self.batch_size = batch_size
        self.name = name
        self.description = description

        # Start time for the archive construction
        self.start_time = time.time()

    def _bold(self, text: str) -> str:
        """Return the given string wrapped in ANSI escape codes for bold
           formatting

           Arguments:
           text (str): string to wrap
        """
        return f"\033[1m{text}\033[0m"

    def _scan_tiles(self) -> Tuple[int, int, int]:
        """Scan the ZXY directory to determine the zoom bounds and the
           total tile count

           Returns:
           tuple: (min_zoom, max_zoom, total_tiles)
                min_zoom (int):    minimum tileset zoom
                max_zoom (int):    maximum tileset zoom
                total_tiles (int): number of tiles in the tileset
        """
        # Determine the minimum and maximum zoom levels
        print("\nDetermining the range of zoom levels.")
        zoom_values = []
        for zoom_dir in self.zxy_dir.iterdir():
            if not zoom_dir.is_dir() or not zoom_dir.name.isdigit():
                continue
            zoom_values.append(int(zoom_dir.name))
        min_zoom = min(zoom_values)
        max_zoom = max(zoom_values)
        print(f"Zoom Range: {min_zoom} to {max_zoom}")

        # Count the total number of tiles
        print("\nCounting the tiles in the ZXY directory.")
        total_tiles = sum(1 for p in self.zxy_dir.rglob(f'*.{self.tile_format}'))
        print(f"Tiles: {total_tiles}")

        return min_zoom, max_zoom, total_tiles

    def _create_mbtiles_schema(self, conn: sqlite3.Connection,
                               min_zoom: int, max_zoom: int) -> None:
        """Create the MBTiles database schema and metadata

           Arguments:
           conn (sqlite3.Connection): database connection
           min_zoom (int):            minimum tileset zoom
           max_zoom (int):            maximum tileset zoom
        """

        # Create tables
        conn.execute('''
            CREATE TABLE metadata (
                name TEXT,
                value TEXT
            )
        ''')

        conn.execute('''
            CREATE TABLE tiles (
                zoom_level INTEGER,
                tile_column INTEGER,
                tile_row INTEGER,
                tile_data BLOB
            )
        ''')

        # Insert metadata
        metadata = [
            ('name', self.name),
            ('type', 'baselayer'),
            ('version', '1.0.0'),
            ('description', self.description),
            ('format', self.tile_format),
            ('minzoom', str(min_zoom)),
            ('maxzoom', str(max_zoom)),
        ]
        conn.executemany('INSERT INTO metadata (name, value) VALUES (?, ?)',
                         metadata)

    def _insert_tiles(self, conn: sqlite3.Connection,
                      total_tiles: int) -> None:
        """Insert the tiles from the ZXY directory into the MBTiles archive

           Arguments:
           conn (sqlite3.Connection): database connection
           total_tiles (int):         number of tiles in the tileset
        """
        # Collect tiles in batches before inserting
        tile_batch = []

        tiles_inserted = 0
        with tqdm(total=total_tiles, desc="Inserting tiles",
                  unit=" tiles", miniters=5000,
                  mininterval=2) as pbar:

            # Step through the zoom directories in a sorted order for
            # progress display...
            for zoom_dir in sorted(self.zxy_dir.iterdir(),
                                   key=lambda x: int(x.name)
                                   if x.name.isdigit() else 0):
                if not zoom_dir.is_dir() or not zoom_dir.name.isdigit():
                    continue
                zoom = int(zoom_dir.name)
                pbar.set_postfix(zoom=zoom)

                # Step through the column / X directories...
                for x_dir in zoom_dir.iterdir():
                    if not x_dir.is_dir() or not x_dir.name.isdigit():
                        continue
                    x = int(x_dir.name)

                    # For each tile file...
                    for tile_file in x_dir.iterdir():
                        if not tile_file.is_file() or \
                           tile_file.name == '.complete':
                            continue

                        # Extract the row / Y from the tile filename or skip
                        # if the filename stem is not a digit
                        y_str = tile_file.stem
                        if not y_str.isdigit():
                            continue
                        y = int(y_str)

                        try:
                            # Read the tile data
                            with open(tile_file, 'rb') as f:
                                tile_data = f.read()

                            # Convert from TMS Y to MBTiles Y
                            # (flip the Y coordinate)
                            mbtiles_y = (2 ** zoom) - 1 - y
                            tile_batch.append((zoom, x, mbtiles_y, tile_data))

                            # Insert and commit batch when it reaches the
                            # batch size
                            if len(tile_batch) == self.batch_size:
                                conn.executemany(
                                    """INSERT INTO tiles (zoom_level,
                                       tile_column, tile_row, tile_data) 
                                       VALUES (?, ?, ?, ?)""",
                                    tile_batch
                                )
                                conn.commit()
                                tile_batch = []

                            # Update the progress bar
                            pbar.update(1)

                            tiles_inserted += 1

                            # Periodically clear some of the WAL file
                            if tiles_inserted % 100000 == 0:
                                conn.execute('PRAGMA wal_checkpoint(PASSIVE)')

                        except Exception as e:
                            print("\nError processing tile "
                                  f"{zoom}/{x}/{y}: {e}")
                            continue

            # Insert and commit any remaining tiles
            if tile_batch:
                conn.executemany(
                    """INSERT INTO tiles (zoom_level, tile_column, tile_row,
                       tile_data) VALUES (?, ?, ?, ?)""",
                    tile_batch
                )
                conn.commit()

    def build_archive(self) -> None:
        """Build the MBTiles archive"""
        print(self._bold(f"Source: {self.zxy_dir}"))
        print(self._bold(f"Output: {self.mbtiles_path}"))
        print(self._bold(f"Batch Size: {self.batch_size} tiles"))

        # Check that the ZXY directory exists
        if not self.zxy_dir.exists():
            print(self._bold(f"\nError: ZXY directory {self.zxy_dir}"
                             " does not exist"))
            sys.exit(1)

        # Scan the directory structure
        min_zoom, max_zoom, total_tiles = self._scan_tiles()
        if total_tiles == 0:
            print(self._bold("\nError: No tiles found in the ZXY directory"))
            sys.exit(1)

        # Create MBTiles archive
        print(self._bold("\nCreating MBTiles archive."))
        try:
            with sqlite3.connect(self.mbtiles_path) as conn:

                # Enable WAL mode for better performance
                conn.execute('PRAGMA journal_mode=WAL')
                conn.execute('PRAGMA synchronous=NORMAL')
                conn.execute('PRAGMA cache_size=-2000000')

                self._create_mbtiles_schema(conn, min_zoom, max_zoom)
                self._insert_tiles(conn, total_tiles)

                # Ensure all transactions are complete
                print("Final commit of tiles to the archive.")
                conn.commit()

                # Transfer changes from the write-ahead logging (WAL) file
                # to the database
                conn.execute('PRAGMA wal_checkpoint(TRUNCATE)')

                # Index the database
                print("Indexing the archive.")
                conn.execute('''
                    CREATE UNIQUE INDEX tile_index ON tiles
                    (zoom_level, tile_column, tile_row)
                ''')

        except Exception as e:
            print(self._bold(f"\nError creating MBTiles archive: {e}"))
            sys.exit(1)

        # Clean up WAL and SHM files
        wal_path = Path(self.mbtiles_path + '-wal')
        shm_path = Path(self.mbtiles_path + '-shm')
        if wal_path.exists():
            wal_path.unlink()
        if shm_path.exists():
            shm_path.unlink()

        # Print runtime
        total_time = time.time() - self.start_time
        print(self._bold("\nArchive is complete!"))
        print(f"Total runtime: {timedelta(seconds=int(total_time))}")

        # Print archive size
        file_size = os.path.getsize(self.mbtiles_path)
        file_size_mb = file_size / (1024 * 1024)
        print(f"Archive size: {file_size_mb:.1f} MB")


@click.command()
@click.argument('zxy_dir', type=click.Path(exists=True, file_okay=False,
                                           path_type=Path))
@click.argument('mbtiles_path', type=click.Path(path_type=Path))
@click.option('--name', default='',
              help='Tileset name')
@click.option('--description', default='',
              help='Tileset description')
@click.option('--format', 'tile_format', default='png',
              type=click.Choice(['png', 'jpg', 'jpeg', 'webp', 'pbf'],
                                case_sensitive=False),
              help='Tile format (default: png)')
@click.option('--batchsize', 'batch_size', default=1000,
              help='Tile batch size for database inserts (default: 1000)')
@click.help_option('--help', '-h')
def main(zxy_dir, mbtiles_path, name, description, tile_format, batch_size):
    """
    Construct an MBTiles archive from a ZXY directory of tiles.

    Arguments:

       ZXY_DIR: ZXY directory of tiles (Z/X/Y.ext)

       MBTILES_PATH: Output path for the MBTiles archive

    Examples:

       # Basic conversion

       zxy-mbtiles ./tiles/ tileset.mbtiles

       # With custom metadata

       zxy-mbtiles ./tiles/ tileset.mbtiles

                   --name "Hillshade tiles"

                   --description "Pre-rendered terrain data"

       # With tile format specified

       zxy-mbtiles ./tiles/ tileset.mbtiles --format jpg
    """
    # Validate that the ZXY directory contains zoom level directories
    zoom_dirs = [d for d in zxy_dir.iterdir() if d.is_dir()
                 and d.name.isdigit()]
    if not zoom_dirs:
        click.echo(f"Error: No zoom level directories found in {zxy_dir}",
                   err=True)
        click.echo("Expected structure: ZXY_DIR/Z/X/Y.ext", err=True)
        sys.exit(1)

    # Check if the output file exists and remove if need be
    if mbtiles_path.exists():
        if click.confirm(f"Output file {mbtiles_path} already exists. "
                         "Overwrite?"):
            mbtiles_path.unlink()
        else:
            sys.exit(1)

    # Convert paths to strings for the converter
    zxy_str = str(zxy_dir)
    mbtiles_str = str(mbtiles_path)

    # Build the MBTiles archive
    constructor = MBTilesConstructor(zxy_str, mbtiles_str, tile_format,
                                     batch_size, name, description)
    constructor.build_archive()


if __name__ == "__main__":
    main()
