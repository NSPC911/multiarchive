# multiarchive

A high level abstraction of multiple archive formats

## Installation

```bash
uv add multiarchive
```

Optional dependency for RAR support:

```bash
uv add rarfile
```

ZStandard support requires the `backports-zstd` package on Python <3.14:

```bash
uv add "backports-zstd; python_version < '3.14'"
```

## Quick Start

```python
from multiarchive import Archive

# Open and inspect
with Archive("archive.zip") as arc:
    print(arc.namelist())  # list of member names
    print(len(arc))        # number of members
    print(arc.size)        # total uncompressed size in bytes

# Extract a single file
with Archive("archive.tar.gz") as arc:
    arc.extract("docs/readme.md", path="./output")

# Read file contents without extracting
with Archive("archive.zip") as arc:
    f = arc.open("config.json")
    content = f.read()
    f.close()

# Iterate over members
with Archive("archive.zip") as arc:
    for name in arc:
        if arc.is_file(name):
            print(f"  {name}")
```

## Supported Formats

| Format  | Read | Write | Extensions                  |
| ------- | ---- | ----- | --------------------------- |
| ZIP     | Yes  | Yes   | `.zip`                      |
| TAR     | Yes  | Yes   | `.tar`                      |
| TAR.GZ  | Yes  | Yes   | `.tgz`, `.tar.gz`           |
| TAR.BZ2 | Yes  | Yes   | `.tbz`, `.tbz2`, `.tar.bz2` |
| TAR.XZ  | Yes  | Yes   | `.tar.xz`, `.tar.lzma`      |
| TAR.ZST | Yes  | Yes   | `.tzst`, `.tar.zst`         |
| RAR     | Yes  | No    | `.rar`                      |

RAR support requires the `rarfile` package and an external `unrar` tool.

## Reading Archives

### Opening

Use the context manager (recommended):

```python
with Archive("file.zip") as arc:
    ...
```

Or the classmethod:

```python
arc = Archive.open_archive("file.zip")
try:
    arc.namelist()
finally:
    arc.close()
```

Reading is supported on all formats, but password-protected archives are not supported and will raise a `ValueError`.
If `algo` isnt explicitly provided, it will attempt to open it as ZIP first, then TAR, then RAR (if `rarfile` is installed). If all fails, it raises a ValueError.

### Listing Members

```python
with Archive("file.zip") as arc:
    names = arc.namelist()  # Just names
    names = arc.members     # alias to namelist

    # extra info (ArchiveMemberInfo objects)
    for info in arc.infolist():
        print(f"{info.name}: {info.uncompressed_size} bytes, mtime={info.mtime}")
```

### Checking Membership

```python
with Archive("file.zip") as arc:
    if "config.json" in arc:
        print("Found!")

    for name in arc:
        if arc.is_file(name):
            ...
        if arc.is_dir(name):
            ...
```

### Extracting

```python
with Archive("file.tar.gz") as arc:
    # Single file
    arc.extract("src/main.py", path="./extracted")
```

### Reading Member Contents

```python
with Archive("file.zip") as arc:
    f = arc.open("data.json")
    if f is not None:
        content = f.read()
        f.close()
```

## Writing Archives

### Creating a New Archive

```python
from multiarchive import Archive

# ZIP
with Archive("output.zip", mode="w") as arc:
    ...

# TAR.GZ with compression level
with Archive("output.tar.gz", mode="w", compression_level=9) as arc:
    ...
```

The format is determined by file extension. Use the `algo` parameter to override:

```python
with Archive("my_archive", mode="w", algo="tar.xz") as arc:
    ...
```

### Compression Levels

| Format  | Range | Default |
| ------- | ----- | ------- |
| ZIP     | 0–9   | 6       |
| TAR.GZ  | 0–9   | 6       |
| TAR.BZ2 | 1–9   | 9       |
| TAR.XZ  | 0–9   | 6       |
| TAR.ZST | 1–22  | 3       |

## File Information Object

The `infolist()` method returns `ArchiveMemberInfo` objects with a unified interface across all formats:

| Field               | Type                            | Description                            |
| ------------------- | ------------------------------- | -------------------------------------- |
| `name`              | `str`                           | Member filename                        |
| `uncompressed_size` | `int`                           | Original file size in bytes            |
| `compressed_size`   | `int \| None`                   | Compressed size (`None` for TAR)       |
| `mtime`             | `float`                         | Modification time as epoch seconds     |
| `mode`              | `int \| None`                   | Unix permission bits                   |
| `is_dir`            | `bool`                          | Whether the member is a directory      |
| `raw`               | `ZipInfo \| TarInfo \| RarInfo` | Original backend object (escape hatch) |

Factory methods for direct conversion (you shouldn't need these in normal usage):

```python
info = ArchiveMemberInfo.from_zipinfo(zip_info)
info = ArchiveMemberInfo.from_tarinfo(tar_info)
info = ArchiveMemberInfo.from_rarinfo(rar_info)
```

## Properties

| Method/Property         | Description                                                     |
| ----------------------- | --------------------------------------------------------------- |
| `members`               | Alias for `namelist()`                                          |
| `size`                  | Total uncompressed size of all members                          |
| `comment` / `comment=`  | Get/set archive comment (ZIP only, raises ValueError otherwise) |

## Error Handling

```python
from multiarchive import Archive, BadArchiveError

try:
    with Archive("corrupted.zip") as arc:
        arc.namelist()
except BadArchiveError as e:
    print(f"Archive error: {e}")
except NotImplementedError as e:
    # password-protected (not supported)
    print(f"Not implemented: {e}")
except ValueError as e:
    # Unknown format
    print(f"Value error: {e}")
except FileNotFoundError:
    print("File not found")
```

## API Reference

### `Archive`

```python
Archive(
    filename: str | Path,
    mode: str = "r",
    compression_level: int | None = None,
)
```

| Parameter           | Description                                       |
| ------------------- | ------------------------------------------------- |
| `filename`          | Path to the archive file                          |
| `mode`              | `'r'` for read, `'w'` for write, `'a'` for append |
| `compression_level` | Compression level (format-dependent)              |

#### Methods

| Method                                                 | Description                            |
| ------------------------------------------------------ | -------------------------------------- |
| `open_archive(cls, filename, mode, compression_level)` | Factory method, returns opened archive |
| `namelist()`                                           | List of member names                   |
| `infolist()`                                           | List of `ArchiveMemberInfo` objects    |
| `extract(member, path)`                                | Extract single member                  |
| `open(member, mode)`                                   | Open member as file-like object        |
| `is_dir(member)`                                       | Check if member is a directory         |
| `is_file(member)`                                      | Check if member is a file              |
| `close()`                                              | Explicitly close the archive           |

### `BadArchiveError`

Raised when an archive file is corrupt or in an unsupported format.

### `ArchiveExtensions`

Frozen dataclass mapping format names to their common file extensions:

```python
ArchiveExtensions.zip     # (".zip",)
ArchiveExtensions.gz      # (".tgz", ".tar.gz")
ArchiveExtensions.xz      # (".tar.xz", ".tar.lzma")
# ... etc
```
