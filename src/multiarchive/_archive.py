import sys
import zipfile
from dataclasses import dataclass
from datetime import datetime
from io import TextIOWrapper
from pathlib import Path
from types import TracebackType
from typing import IO, List, Literal, TypeAlias

try:
    import bz2 as bzip2
except ImportError:
    bzip2 = None  # ty: ignore
try:
    import gzip
except ImportError:
    gzip = None  # ty: ignore
try:
    import lzma
except ImportError:
    lzma = None  # ty: ignore
try:
    import rarfile
except ImportError:
    rarfile = None  # ty: ignore

try:
    if sys.version_info.major == 3 and sys.version_info.minor <= 13:
        from backports.zstd import tarfile  # noqa  # ty: ignore
    else:
        import tarfile
except ImportError:
    import tarfile

    zstd_available = False
else:
    zstd_available = True


# Type Aliases
if rarfile is not None:
    InfoType: TypeAlias = zipfile.ZipInfo | tarfile.TarInfo | rarfile.RarInfo
    InfoList: TypeAlias = (
        list[zipfile.ZipInfo] | list[tarfile.TarInfo] | list[rarfile.RarInfo]
    )
    ArchiveType: TypeAlias = zipfile.ZipFile | tarfile.TarFile | rarfile.RarFile
    BadArchive = (zipfile.BadZipFile, tarfile.TarError, rarfile.BadRarFile)
else:
    InfoType: TypeAlias = zipfile.ZipInfo | tarfile.TarInfo
    InfoList: TypeAlias = list[zipfile.ZipInfo] | list[tarfile.TarInfo]
    ArchiveType: TypeAlias = zipfile.ZipFile | tarfile.TarFile
    BadArchive = (zipfile.BadZipFile, tarfile.TarError)
if gzip is not None:
    CompressFileObjType: TypeAlias = IO[bytes] | TextIOWrapper | gzip.GzipFile
else:
    CompressFileObjType: TypeAlias = IO[bytes] | TextIOWrapper


class BadArchiveError(Exception):
    """Custom exception for handling bad or unsupported archive files."""


# hard code because i dont want to get the file headers to identify them
@dataclass(frozen=True)
class ArchiveExtensions:
    zip = (".zip",)
    rar = (".rar",)
    tar = (".tar",)
    gz = (".tgz", ".tar.gz")
    bz2 = (".tbz", ".tbz2", ".tar.bz2")
    xz = (".tar.xz", ".tar.lzma")
    zst = (".tzst", ".tar.zst")


@dataclass(frozen=True)
class ArchiveMemberInfo:
    """Unified metadata for archive members with a consistent interface.

    The `raw` attribute provides direct access to the underlying backend-specific
    info object (ZipInfo, TarInfo, or RarInfo) when advanced or format-specific
    features are needed.
    """

    name: str
    uncompressed_size: int
    compressed_size: int | None
    mtime: float
    mode: int | None
    is_dir: bool
    raw: InfoType

    @classmethod
    def from_zipinfo(cls, info: zipfile.ZipInfo) -> "ArchiveMemberInfo":
        mtime_dt = datetime(*info.date_time)
        return cls(
            name=info.filename,
            uncompressed_size=info.file_size,
            compressed_size=info.compress_size,
            mtime=mtime_dt.timestamp(),
            mode=(info.external_attr >> 16) or None,
            is_dir=info.is_dir(),
            raw=info,
        )

    @classmethod
    def from_tarinfo(cls, info: tarfile.TarInfo) -> "ArchiveMemberInfo":
        return cls(
            name=info.name,
            uncompressed_size=info.size,
            compressed_size=None,
            mtime=float(info.mtime or 0.0),
            mode=info.mode,
            is_dir=info.isdir(),
            raw=info,
        )

    @classmethod
    def from_rarinfo(cls, info: "rarfile.RarInfo") -> "ArchiveMemberInfo":
        if info.mtime is not None:
            mtime = info.mtime.timestamp()
        elif info.date_time is not None:
            mtime = datetime(*info.date_time).timestamp()
        else:
            mtime = 0.0
        assert info.filename is not None
        assert info.file_size is not None
        assert info.compress_size is not None
        return cls(
            name=info.filename,
            uncompressed_size=info.file_size,
            compressed_size=info.compress_size,
            mtime=mtime,
            mode=info.mode,
            is_dir=info.is_dir(),
            raw=info,
        )


class Archive:
    """Unified handler for ZIP, TAR and RAR files with context manager support."""

    def __init__(
        self,
        filename: str | Path,
        algo: Literal["zip", "tar", "rar", "tar.gz", "tar.bz2", "tar.xz", "tar.zst"]
        | None = None,
        mode: str = "r",
        compression_level: int | None = None,
    ) -> None:
        """Initialize the archive handler.

        Args:
            filename: Path to the archive file
            mode: File access mode ('r' for read, 'w' for write, 'a' for append)
            compression_level: Compression level (ZIP: 0-9, TAR gzip: 0-9, TAR bzip2: 1-9)
                             If None, uses default compression

        Raises:
            ValueError: If mode is not supported or compression_level is out of range
        """  # noqa: DOC502
        self.filename = str(filename)
        self.mode = mode
        self.compression_level = compression_level
        self.algo = algo
        self._archive: ArchiveType | None = None
        self._archive_type: Literal["zip", "rar", "tar"] | None = None
        self._compress_file_obj: CompressFileObjType | None = None

    @classmethod
    def open_archive(
        cls,
        filename: str | Path,
        mode: str = "r",
        compression_level: int | None = None,
    ) -> "Archive":
        """Create and open an archive without using a context manager.

        This is a factory method alternative to using __init__ directly.

        Args:
            filename: Path to the archive file
            mode: File access mode ('r' for read, 'w' for write, 'a' for append)
            compression_level: Compression level (ZIP: 0-9, TAR gzip: 0-9, TAR bzip2: 1-9)

        Returns:
            Opened Archive instance ready for use

        Raises:
            FileNotFoundError: If the archive file doesn't exist (for read mode)
            ValueError: If file extension is not recognized or compression_level is invalid
            BadArchiveError: If the archive cannot be opened due to format errors

        Examples:
            >>> archive = Archive.open_archive("file.zip")
            >>> archive.namelist()
            ['file1.txt', 'file2.txt']
            >>> archive.close()
        """
        archive = cls(filename, mode=mode, compression_level=compression_level)
        archive._detect_and_open()
        return archive

    def __enter__(self) -> "Archive":
        """Context manager entry - opens the archive.

        Returns:
            Self for method chaining in with statement
        """
        self._detect_and_open()
        return self

    def __exit__(
        self,
        exc_type: type | None,
        exc_val: Exception | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """Context manager exit - closes the archive.

        Args:
            exc_type: Exception type if an exception occurred
            exc_val: Exception value if an exception occurred
            exc_tb: Traceback if an exception occurred
        """
        if self._archive:
            self._archive.close()
        if self._compress_file_obj:
            self._compress_file_obj.close()

    def _detect_and_open(self) -> None:
        """Detect file type and open appropriate handler.

        For read mode, attempts to open as ZIP, then RAR, then TAR by trying each
        format and catching format-specific errors. For write mode, uses file
        extension to determine the format.

        Raises:
            FileNotFoundError: If the archive file doesn't exist (for read mode)
            ValueError: If file extension is not recognized or compression_level is invalid
            BadArchiveError: If the archive cannot be opened due to format errors
        """
        try:
            if self.mode == "r":
                self._detect_and_open_read()
            else:
                self._detect_and_open_write()
        except BadArchive as exc:
            raise BadArchiveError(f"Failed to open archive. {exc}") from exc
        except (FileNotFoundError, ValueError):
            raise

    def _detect_and_open_read(self) -> None:
        """Attempt to open archive for reading by trying each format.

        Tries ZIP first, then RAR, then TAR. Uses actual file content detection
        rather than relying on file extensions.

        Raises:
            FileNotFoundError: If the archive file doesn't exist
            NotImplementedError: If the archive is password-protected (for ZIP and RAR)
            ValueError: If the file is not a valid ZIP, RAR, or TAR archive
        """  # noqa: DOC502
        # Try ZIP first
        try:
            archive = zipfile.ZipFile(self.filename, "r")
            # Check for password protection
            if any(zinfo.flag_bits & 0x1 for zinfo in archive.infolist()):
                archive.close()
                raise NotImplementedError("Password-protected ZIP files are not supported")
            self._archive = archive
            self._archive_type = "zip"
            return
        except zipfile.BadZipFile:
            pass

        # Try RAR
        try:
            archive = rarfile.RarFile(self.filename, "r")
            # Check for password protection
            if archive.needs_password():
                archive.close()
                raise NotImplementedError("Password-protected RAR files are not supported")
            self._archive = archive
            self._archive_type = "rar"
            return
        except rarfile.NotRarFile:
            pass

        # Try TAR (with auto-detection for compression)
        try:
            self._archive = tarfile.open(self.filename, "r:*")  # noqa: SIM115
            self._archive_type = "tar"
            return
        except tarfile.TarError:
            pass

        raise ValueError(
            f"Cannot open '{self.filename}': not a valid ZIP, RAR, or TAR archive"
        )

    def _detect_and_open_write(self) -> None:
        """Open archive for writing based on file extension.

        Raises:
            ValueError: If file extension is not recognized or compression_level is invalid
        """
        filename_lower = self.filename.lower()

        if filename_lower.endswith(ArchiveExtensions.zip) or (self.algo == "zip"):
            self._archive_type = "zip"
            if self.compression_level is not None:
                if not (0 <= self.compression_level <= 9):
                    raise ValueError("ZIP compression level must be between 0-9")
                self._archive = zipfile.ZipFile(
                    self.filename, self.mode, compresslevel=self.compression_level
                )
            else:
                self._archive = zipfile.ZipFile(self.filename, self.mode)
        elif filename_lower.endswith(ArchiveExtensions.rar) or (self.algo == "rar"):
            raise ValueError("RAR files can only be opened in read mode ('r')")
        else:
            # Assume it's a tar file
            self._archive_type = "tar"
            tar_mode = self._get_tar_write_mode()
            if self.compression_level is not None:
                self._archive = self._open_tar_with_compression(tar_mode)
            else:
                self._archive = tarfile.open(self.filename, tar_mode)  # noqa: SIM115

    def _get_tar_write_mode(self) -> Literal["w:gz", "w:bz2", "w:xz", "w:zst", "w"]:
        """Determine tar write mode based on file extension.

        Returns:
            Appropriate tarfile mode string for writing
        """
        filename_lower = self.filename.lower()
        if filename_lower.endswith(ArchiveExtensions.gz) or (self.algo == "tar.gz"):
            return "w:gz"
        elif filename_lower.endswith(ArchiveExtensions.bz2) or (self.algo == "tar.bz2"):
            return "w:bz2"
        elif filename_lower.endswith(ArchiveExtensions.xz) or (self.algo == "tar.xz"):
            return "w:xz"
        elif filename_lower.endswith(ArchiveExtensions.zst) or (self.algo == "tar.zst"):
            return "w:zst"
        else:
            return "w"

    def _open_tar_with_compression(
        self, tar_mode: Literal["w:gz", "w:bz2", "w:xz", "w:zst", "w"]
    ) -> tarfile.TarFile:
        """Open TAR file with specified compression level.

        Args:
            tar_mode: TAR mode string (e.g., 'w:gz', 'w:bz2')

        Returns:
            Opened TarFile with compression level applied

        Raises:
            ValueError: If compression level is invalid for the compression type
            ModuleNotFoundError: If the required compression module is not available
        """
        assert self.compression_level is not None

        if ":gz" in tar_mode:
            if not (0 <= self.compression_level <= 9):
                raise ValueError("Gzip compression level must be between 0-9")
            self._compress_file_obj = gzip.open(  # noqa: SIM115
                self.filename, self.mode + "b", compresslevel=self.compression_level
            )
            return tarfile.open(fileobj=self._compress_file_obj, mode="w")

        elif ":bz2" in tar_mode:
            if not (1 <= self.compression_level <= 9):
                raise ValueError("bzip2 compression level must be between 1-9")
            if bzip2 is None:
                raise ModuleNotFoundError("bzip2 module is not available")
            self._compress_file_obj = bzip2.open(  # noqa: SIM115
                self.filename, self.mode + "b", compresslevel=self.compression_level
            )
            return tarfile.open(fileobj=self._compress_file_obj, mode="w")

        elif ":xz" in tar_mode:
            if not (0 <= self.compression_level <= 9):
                raise ValueError("xz compression level must be between 0-9")
            if lzma is None:
                raise ModuleNotFoundError("lzma module is not available")
            xz_file = lzma.open(  # noqa: SIM115
                self.filename, self.mode + "b", preset=self.compression_level
            )
            return tarfile.open(fileobj=xz_file, mode="w")
        elif ":zst" in tar_mode:
            if not (1 <= self.compression_level <= 22):
                raise ValueError("zstd compression level must be between 1-22")
            if not zstd_available:
                raise ModuleNotFoundError("zstd compression is not available")
            return tarfile.open(self.filename, tar_mode, level=self.compression_level)
        else:
            return tarfile.open(self.filename, mode="w")

    def infolist(
        self,
    ) -> list[ArchiveMemberInfo]:
        """Return list of archive members wrapped in ArchiveMemberInfo.

        Returns:
            List of ArchiveMemberInfo objects with unified metadata

        Raises:
            RuntimeError: If archive is not opened
            BadArchiveError: If the archive cannot be listed due to any archive related errors
            FileNotFoundError: If the file is no longer available
        """
        if not self._archive:
            raise RuntimeError("Archive not opened")

        try:
            match self._archive_type:
                case "rar":
                    assert isinstance(self._archive, rarfile.RarFile)
                    return [
                        ArchiveMemberInfo.from_rarinfo(i)
                        for i in self._archive.infolist()
                    ]
                case "zip":
                    assert isinstance(self._archive, zipfile.ZipFile)
                    return [
                        ArchiveMemberInfo.from_zipinfo(i)
                        for i in self._archive.infolist()
                    ]
                case _:
                    assert isinstance(self._archive, tarfile.TarFile)
                    return [
                        ArchiveMemberInfo.from_tarinfo(i)
                        for i in self._archive.getmembers()
                    ]
        except BadArchive as exc:
            raise BadArchiveError(f"Failed to open archive. {exc}") from exc
        except FileNotFoundError:
            raise

    def namelist(self) -> List[str]:
        """Return list of member names.

        Returns:
            List of strings containing all member file/directory names in the archive

        Raises:
            RuntimeError: If archive is not opened
            BadArchiveError: If the archive cannot be listed due to any archive related errors
            FileNotFoundError: If the file is no longer available
        """
        if not self._archive:
            raise RuntimeError("Archive not opened")

        try:
            match self._archive_type:
                case "zip":
                    assert isinstance(self._archive, zipfile.ZipFile)
                    return self._archive.namelist()
                case "rar":
                    assert isinstance(self._archive, rarfile.RarFile)
                    return self._archive.namelist()
                case _:
                    assert isinstance(self._archive, tarfile.TarFile)
                    return self._archive.getnames()
        except BadArchive as exc:
            raise BadArchiveError(f"Failed to open archive. {exc}") from exc
        except FileNotFoundError:
            raise

    def extract(
        self,
        member: str | InfoType,
        path: str | Path = "",
    ) -> str:
        """Extract a single member to the specified path.

        Args:
            member: Name of the file to extract, or ZipInfo/TarInfo/RarInfo object
            path: Directory to extract to. If None, extracts to current directory

        Returns:
            Path to the extracted file

        Raises:
            RuntimeError: If archive is not opened
            BadArchiveError: If the extraction fails due to archive related errors
            FileNotFoundError: If the file is no longer available
        """
        if not self._archive:
            raise RuntimeError("Archive not opened")

        try:
            match self._archive_type:
                case "rar":
                    assert isinstance(self._archive, rarfile.RarFile)
                    if isinstance(member, rarfile.RarInfo):
                        member_filename = str(member.filename)
                    else:
                        member_filename = str(member)
                    self._archive.extract(member, path)
                    return str(Path(path or ".") / member_filename)
                case "zip":
                    assert isinstance(self._archive, zipfile.ZipFile)
                    member_arg = (
                        member
                        if isinstance(member, (str, zipfile.ZipInfo))
                        else str(member)
                    )
                    return self._archive.extract(member_arg, path)
                case _:
                    assert isinstance(self._archive, tarfile.TarFile)
                    member_arg = (
                        member
                        if isinstance(member, (str, tarfile.TarInfo))
                        else str(member)
                    )
                    result = self._archive.extract(member_arg, path)
                    return (
                        str(result)
                        if result
                        else str(Path(path or ".") / str(member_arg))
                    )
        except BadArchive as exc:
            raise BadArchiveError(f"Failed to extract member. {exc}") from exc
        except FileNotFoundError:
            raise

    def open(
        self,
        member: str | InfoType,
        mode: Literal["r", "w"] = "r",
    ) -> IO[bytes] | None:
        """Open a member file for reading.

        Args:
            member: Name of the file to open, or ZipInfo/TarInfo/RarInfo object
            mode: File open mode (only 'r' supported for TAR and RAR files)

        Returns:
            File-like object for reading the member's contents, or None if member
            is a directory or cannot be opened

        Raises:
            RuntimeError: If archive is not opened
            ValueError: If a RAR file is attempted to be opened in anything that isn't read mode
            BadArchiveError: If the member cannot be opened due to archive related errors
            FileNotFoundError: If the file is no longer available
        """
        if not self._archive:
            raise RuntimeError("Archive not opened")

        try:
            match self._archive_type:
                case "zip":
                    assert isinstance(self._archive, zipfile.ZipFile)
                    member_arg = (
                        member
                        if isinstance(member, (str, zipfile.ZipInfo))
                        else str(member)
                    )
                    return self._archive.open(member_arg, mode)
                case "rar":
                    assert isinstance(self._archive, rarfile.RarFile)
                    if mode != "r":
                        raise ValueError(
                            "RAR members can only be opened in read mode ('r')"
                        )
                    member_arg = (
                        member
                        if isinstance(member, (str, rarfile.RarInfo))
                        else str(member)
                    )
                    return self._archive.open(member_arg, mode)
                case _:
                    assert isinstance(self._archive, tarfile.TarFile)
                    member_arg = (
                        member
                        if isinstance(member, (str, tarfile.TarInfo))
                        else str(member)
                    )
                    return self._archive.extractfile(member_arg)
        except BadArchive as exc:
            raise BadArchiveError(f"Failed to open member. {exc}") from exc
        except FileNotFoundError:
            raise

    @property
    def members(self) -> List[str]:
        """Return list of member names (alias for namelist()).

        Returns:
            List of strings containing all member file/directory names
        """
        return self.namelist()

    @property
    def size(self) -> int:
        """Return total uncompressed size of all members in bytes.

        Returns:
            Total uncompressed size across all archive members

        Raises:
            RuntimeError: If archive is not opened
        """
        if not self._archive:
            raise RuntimeError("Archive not opened")

        match self._archive_type:
            case "zip":
                assert isinstance(self._archive, zipfile.ZipFile)
                return sum(info.file_size for info in self._archive.infolist())
            case "rar":
                assert isinstance(self._archive, rarfile.RarFile)
                return sum(info.file_size for info in self._archive.infolist())
            case _:
                assert isinstance(self._archive, tarfile.TarFile)
                return sum(info.size for info in self._archive.getmembers())

    @property
    def comment(self) -> bytes:
        """Get the archive comment (ZIP only).

        Returns:
            Archive comment as bytes, or empty bytes for non-ZIP archives

        Raises:
            RuntimeError: If archive is not opened
        """
        if not self._archive:
            raise RuntimeError("Archive not opened")

        if self._archive_type == "zip":
            assert isinstance(self._archive, zipfile.ZipFile)
            return self._archive.comment
        return b""

    @comment.setter
    def comment(self, value: bytes) -> None:
        """Set the archive comment (ZIP only).

        Args:
            value: Comment to set as bytes

        Raises:
            RuntimeError: If archive is not opened
            ValueError: If attempting to set comment on non-ZIP archive
        """
        if not self._archive:
            raise RuntimeError("Archive not opened")

        if self._archive_type != "zip":
            raise ValueError("Archive comment is only supported for ZIP files")

        assert isinstance(self._archive, zipfile.ZipFile)
        self._archive.comment = value

    def __iter__(self):
        """Iterate over member names.

        Yields:
            String containing each member file/directory name
        """
        yield from self.namelist()

    def __contains__(self, member: str) -> bool:
        """Check if a member exists in the archive.

        Args:
            member: Name of the member to check

        Returns:
            True if member exists in archive, False otherwise
        """
        return member in self.namelist()

    def __len__(self) -> int:
        """Return number of members in the archive.

        Returns:
            Number of files/directories in the archive
        """
        return len(self.namelist())

    def close(self) -> None:
        """Explicitly close the archive.

        Safe to call multiple times. Closes both the archive and any
        compression file objects.
        """
        if self._archive:
            self._archive.close()
            self._archive = None
        if self._compress_file_obj:
            self._compress_file_obj.close()
            self._compress_file_obj = None

    def is_dir(self, member: str | InfoType) -> bool:
        """Check if a member is a directory.

        Args:
            member: Name of the member or its info object

        Returns:
            True if the member is a directory, False otherwise

        Raises:
            RuntimeError: If archive is not opened
        """
        if not self._archive:
            raise RuntimeError("Archive not opened")

        match self._archive_type:
            case "zip":
                assert isinstance(self._archive, zipfile.ZipFile)
                info = (
                    member
                    if isinstance(member, zipfile.ZipInfo)
                    else self._archive.getinfo(str(member))
                )
                return info.is_dir()
            case "rar":
                assert isinstance(self._archive, rarfile.RarFile)
                info = (
                    member
                    if isinstance(member, rarfile.RarInfo)
                    else self._archive.getinfo(str(member))
                )
                return info.is_dir()
            case _:
                assert isinstance(self._archive, tarfile.TarFile)
                info = (
                    member
                    if isinstance(member, tarfile.TarInfo)
                    else self._archive.getmember(member)
                )
                return info.isdir()

    def is_file(self, member: str | InfoType) -> bool:
        """Check if a member is a regular file.

        Args:
            member: Name of the member or its info object

        Returns:
            True if the member is a file (not a directory), False otherwise

        Raises:
            RuntimeError: If archive is not opened
        """
        return not self.is_dir(member)
