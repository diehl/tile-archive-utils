#!/usr/bin/env python3
"""
PMTiles Extractor

This script leverages gdal_cp.py from the GDAL Python library to extract tiles
from a PMTiles archive into a ZXY directory structure.

To avoid memory leaks that occasionally occur with large archives, this script
iterates through the zoom levels and incrementally extracts tiles for each
X directory at the current zoom level.
"""

import os
import sys
import time
import click
import shutil
import subprocess

from tqdm import tqdm
from pathlib import Path
from datetime import timedelta


class PMTilesExtractor:
    """Extracts tiles from a PMTiles archive into a ZXY directory structure."""

    def __init__(self, pmtiles_path: str, output_dir: str) -> None:
        """Initialize a new PMTilesExtractor instance

           Arguments:
           pmtiles_path (str):           path to the PMTiles archive
           output_dir (str):             path to the output directory
        """
        self.pmtiles_path = pmtiles_path
        self.output_dir = output_dir

        # Path to the bundled gdal_cp.py script
        package_dir = Path(__file__).parent
        self.gdal_script = str(package_dir / "gdal_cp.py")

        # Start time for the extraction
        self.start_time = time.time()

    def _bold(self, text: str) -> str:
        """Return the given string wrapped in ANSI escape codes for bold
           formatting

           Arguments:
           text (str): string to wrap
        """
        return f"\033[1m{text}\033[0m"

    def is_directory_complete(self, zoom: int, x: int) -> bool:
        """Check if the directory extraction is complete

           Arguments:
           zoom (int): zoom level
           x (int):    column index

           Returns a boolean indicating whether or not the directory extraction
           is complete for the referenced column at the specified zoom level
        """
        # Check for the presence of a hidden file indicating the extraction
        # is complete
        marker_path = f"{self.output_dir}/{zoom}/{x}/.complete"
        return os.path.exists(marker_path)

    def mark_directory_complete(self, zoom: int, x: int) -> None:
        """Mark a directory with a hidden file to indicate the extraction
           is complete

           Arguments:
           zoom (int): zoom level
           x (int):    column index
        """
        marker_path = f"{self.output_dir}/{zoom}/{x}/.complete"
        with open(marker_path, 'w') as f:
            f.write(str(time.time()))

    def extract_directory(self, zoom: int, x: int) -> \
            tuple[bool, int, str | None]:
        """Extract a single column directory

           Arguments:
           zoom (int): zoom level
           x (int):    column index

           Returns a (bool, int, str) tuple indicating whether or not the
           extraction was successfully completed, the extraction duration
           in seconds and any relevant error message if the extraction was
           unsuccessful
        """
        # Path to the source directory in the archive that is passed
        # to gdal_cp.py
        src = f"/vsipmtiles/{self.pmtiles_path}/{zoom}/{x}"

        # Destination directory for the tiles
        dst = f"{self.output_dir}/{zoom}/{x}"

        # Remove the destination directory if it exists from a prior
        # extraction attempt
        if os.path.exists(dst):
            shutil.rmtree(dst)

        # Create the parent directory if necessary
        parent_dir = f"{self.output_dir}/{zoom}"
        os.makedirs(parent_dir, exist_ok=True)

        # Construct the command for the gdal_cp.py run
        cmd = [sys.executable, self.gdal_script, "-r", src, dst]

        # Run the subprocess
        start_time = time.time()
        try:
            result = subprocess.run(cmd,
                                    capture_output=True,
                                    text=True,
                                    timeout=600)  # 10 minute timeout
            elapsed = time.time() - start_time

            if result.returncode == 0:
                # Mark the directory as complete after a successful extraction
                self.mark_directory_complete(zoom, x)

                return True, elapsed, None
            else:
                return False, elapsed, result.stderr

        # If the extraction process times out...
        except subprocess.TimeoutExpired:
            return False, 600, "Timeout after 10 minutes"

        # If another exception occurred...
        except Exception as e:
            return False, 0, str(e)

    def process_zoom_level(self, zoom: int) -> None:
        """Process all column directories for the specified zoom level

           Arguments:
           zoom (int): zoom level
        """
        # Number of column directories
        num_col_directories = 2 ** zoom

        # Find which column directories need extraction
        to_extract, completed = [], 0
        for x in range(num_col_directories):
            if self.is_directory_complete(zoom, x):
                completed += 1
            else:
                to_extract.append(x)

        # Check to see if there are any directories to extract. If not, return.
        if not to_extract:
            print(f"\nZoom {zoom}: All {num_col_directories} directories "
                  f"have been extracted ✓")
            return

        print(self._bold(f"\nZoom Level {zoom}"))
        print(f"  Total: {num_col_directories} directories")
        print(f"  Completed: {completed}")
        print(f"  Remaining: {len(to_extract)}")

        # Extract the directories
        zoom_start = time.time()
        successes = 0
        failures = []
        with tqdm(total=len(to_extract),
                  desc=f"Zoom {zoom}",
                  unit="dir",
                  bar_format=("{desc}: {percentage:3.0f}%|{bar}| "
                              "{n_fmt}/{total_fmt} "
                              "[{elapsed}<{remaining}]")) as pbar:

            for x in to_extract:
                pbar.set_description(f"Zoom {zoom} [X={x}]")

                success, elapsed, error = self.extract_directory(zoom, x)

                if success:
                    successes += 1
                else:
                    failures.append((x, error))

                pbar.update(1)
                pbar.set_postfix(ok=successes, fail=len(failures),
                                 last=f"{elapsed:.1f}s")

        zoom_elapsed = time.time() - zoom_start

        # Display summary statistics and any error messages from the extraction
        print(f"\n  Time: {timedelta(seconds=int(zoom_elapsed))}")
        print(f"  ✓ Extracted: {successes}")
        if failures:
            print(f"  ✗ Failed: {len(failures)}")
            for x, error in failures[:3]:  # Show first 3 errors
                print(f"    X={x}: {error[:80] if error else 'Unknown error'}")
            if len(failures) > 3:
                print(f"    ... and {len(failures) - 3} more failures")

    def run(self, min_zoom: int, max_zoom: int) -> None:
        """Run the extraction process

           Arguments:
           min_zoom (int): minimum zoom level to process
           max_zoom (int): maximum zoom level to process
        """
        print(self._bold(f"Source: {self.pmtiles_path}"))
        print(self._bold(f"Output: {self.output_dir}"))

        # Ensure the GDAL script exists
        if not os.path.exists(self.gdal_script):
            print(self._bold(f"\nError: {self.gdal_script} not found"))
            sys.exit(1)

        # Count the number of column directories that are already complete
        total_dirs = sum(2 ** z for z in range(min_zoom, max_zoom + 1))
        completed_dirs_at_start = 0
        for zoom in range(min_zoom, max_zoom + 1):
            for x in range(2 ** zoom):
                if self.is_directory_complete(zoom, x):
                    completed_dirs_at_start += 1

        if completed_dirs_at_start > 0:
            print(self._bold(f"\nStarting extraction "
                             f"({completed_dirs_at_start}/{total_dirs} "
                             f"directories already complete)."))

        try:
            # Process each zoom level
            for zoom in range(min_zoom, max_zoom + 1):
                self.process_zoom_level(zoom)

            print(self._bold("\nExtraction complete!"))

        except KeyboardInterrupt:
            print(self._bold("\n\nKeyboard interrupt! Run again to complete "
                             "the extraction."))
            sys.exit(1)

        # Compute and print the total runtime
        total_time = time.time() - self.start_time
        print(f"Total runtime: {timedelta(seconds=int(total_time))}")

        # Compute the total number of directories extracted
        total_dirs_extracted = 0
        for zoom in range(min_zoom, max_zoom + 1):
            for x in range(2 ** zoom):
                if self.is_directory_complete(zoom, x):
                    total_dirs_extracted += 1

        # Print the number of directories extracted and the average
        # extraction rate
        newly_extracted_dirs = total_dirs_extracted - completed_dirs_at_start
        if newly_extracted_dirs > 0 and total_time > 0:
            rate = newly_extracted_dirs / (total_time / 60)
            print(f"Extracted: {newly_extracted_dirs} directories")
            print(f"Average rate: {rate:.1f} directories/minute")


@click.command()
@click.argument('pmtiles_path', type=click.Path(exists=True, dir_okay=False, 
                                                path_type=Path))
@click.argument('output_dir', type=click.Path(path_type=Path))
@click.argument('min_zoom', type=int)
@click.argument('max_zoom', type=int)
@click.help_option('--help', '-h')
def main(pmtiles_path, output_dir, min_zoom, max_zoom):
    """Extract tiles from a PMTiles archive into a ZXY directory structure.

    Arguments:

       PMTILES_PATH: Path to the PMTiles archive

       OUTPUT_DIR: Directory where the extracted tiles will be written

       MIN_ZOOM: Minimum zoom level to extract

       MAX_ZOOM: Maximum zoom level to extract

    Example:

       # Extract zoom levels 0-10 from map.pmtiles to ./tiles/

       pmtiles-zxy map.pmtiles ./tiles/ 0 10
    """
    # Check if GDAL is installed
    try:
        from osgeo import gdal
    except ImportError:
        print(self._bold(f"\nError: GDAL Python bindings not found"))
        print("  Check the README.md file for installation options")
        print("  conda install -c conda-forge gdal is recommended")
        sys.exit(1)

    # Validate zoom level arguments
    if min_zoom < 0:
        raise click.ClickException("Error: min_zoom must be >= 0")

    if max_zoom < min_zoom:
        raise click.ClickException("Error: max_zoom must be >= min_zoom")

    # Create the output directory if it doesn't exist
    output_dir.mkdir(parents=True, exist_ok=True)

    # Convert paths to strings for the extractor
    pmtiles_str = str(pmtiles_path)
    output_str = str(output_dir)

    # Run the extractor
    extractor = PMTilesExtractor(pmtiles_str, output_str)
    extractor.run(min_zoom, max_zoom)


if __name__ == "__main__":
    main()
