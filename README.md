# Tile Archive Utils

This package provides command-line utilities supporting the extraction of tiles from PMTiles archives
to ZXY directories and the construction of MBTiles archives from ZXY directories. Combined with the
[PMTiles command-line utilities](https://docs.protomaps.com/pmtiles/cli), this package makes it possible 
to extract tiles from a PMTiles archive, transform the tiles, and assemble the transformed tiles 
into a derivative PMTiles archive. 

## Installation

### Install GDAL + Python bindings (Required)

**Option 1: Using conda (Recommended)**
```bash
conda install -c conda-forge gdal
```
This installs both the GDAL library and the Python bindings, eliminating the risk of version mismatch.

**Option 2: Using system package manager + pip**
```bash
# Ubuntu/Debian
sudo apt-get install gdal-bin libgdal-dev
pip install gdal

# macOS with Homebrew  
brew install gdal
pip install gdal
```
Ensure the GDAL library and Python binding versions match for proper execution.

*Note that Docker is discouraged for use with this package as the volume of file I/O
significantly degrades performance when running within a VM.*

### Install tile-archive-utils

```bash
pip install tile-archive-utils
```

## Commands

After installation, you'll have access to two command-line tools:

### pmtiles-zxy

Extracts tiles from a PMTiles archive into a ZXY hierarchical directory structure.

```bash
pmtiles-zxy <PMTiles archive> <output directory> <min zoom> <max zoom>
```

**Example:**
```bash
# Extract zoom levels 0-10 from map.pmtiles to the directory tiles
pmtiles-zxy tileset.pmtiles tiles 0 10
```

**Features:**
- Robust extraction with detailed error reporting 
- Progress tracking with tqdm
- Seamless continuation following interruptions
- Memory-efficient processing by zoom level
- Built-in GDAL script bundling

### zxy-mbtiles

Converts ZXY hierarchical directory structures into MBTiles archives.

```bash
zxy-mbtiles <ZXY directory> <output MBTiles file> [options]
```

**Options:**
- `--name <string>`: Tileset name
- `--description <string>`: Tileset description
- `--format <format>`: Tile format (default: png, supports: png, jpg, webp, pbf)
- `--batchsize <integer>`: Tile batch size for database inserts (default: 1000)

**Examples:**
```bash
# Basic conversion
zxy-mbtiles tiles tileset.mbtiles

# With custom metadata
zxy-mbtiles tiles tileset.mbtiles --name "Hillshade tiles" --description "Pre-rendered terrain data"

# With tile format and batch size specified
zxy-mbtiles tiles tileset.mbtiles --format jpg --batchsize 10000
```

**Features:**
- Optimized SQLite database creation
- Progress tracking with tqdm
- Multiple tile format support

## Directory Structure

The package has the following structure:

```
tile-archive-utils/
├── pyproject.toml
├── README.md
├── src/
│   └── tile_archive_utils/
│       ├── __init__.py
│       ├── pmtiles_to_zxy.py    # PMTiles → ZXY converter
│       ├── zxy_to_mbtiles.py    # ZXY → MBTiles converter
│       └── gdal_cp.py           # Bundled GDAL utility
```

## Requirements

- Python 3.10+
- GDAL + Python bindings
- tqdm
- click

## ZXY Directory Format

The ZXY format follows this hierarchical structure:
```
tiles/
├── 0/
│   └── 0/
│       └── 0.png
├── 1/
│   ├── 0/
│   │   ├── 0.png
│   │   └── 1.png
│   └── 1/
│       ├── 0.png
│       └── 1.png
└── ...
```

Where:
- First level: Zoom level (Z)
- Second level: Column/X coordinate
- Files: Row/Y coordinate with tile extension