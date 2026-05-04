import tarfile
import zipfile
from dataclasses import replace
from datetime import datetime, timezone

import pytest

from multiarchive._archive import ArchiveMemberInfo


@pytest.fixture
def sample_zipinfo():
    zi = zipfile.ZipInfo("test/file.txt", date_time=(2024, 1, 15, 10, 30, 0))
    zi.file_size = 1024
    zi.compress_size = 512
    zi.external_attr = 0o644 << 16
    return zi


@pytest.fixture
def sample_zipinfo_dir():
    zi = zipfile.ZipInfo("test/dir/", date_time=(2024, 1, 15, 10, 30, 0))
    zi.file_size = 0
    zi.compress_size = 0
    zi.external_attr = 0o755 << 16
    return zi


@pytest.fixture
def sample_tarinfo():
    ti = tarfile.TarInfo(name="test/file.txt")
    ti.size = 2048
    ti.mtime = 1705312200.0
    ti.mode = 0o644
    ti.type = tarfile.REGTYPE
    return ti


@pytest.fixture
def sample_tarinfo_dir():
    ti = tarfile.TarInfo(name="test/dir/")
    ti.size = 0
    ti.mtime = 1705312200.0
    ti.mode = 0o755
    ti.type = tarfile.DIRTYPE
    return ti


class TestArchiveMemberInfoFromZipinfo:
    def test_basic_fields(self, sample_zipinfo):
        info = ArchiveMemberInfo.from_zipinfo(sample_zipinfo)
        assert info.name == "test/file.txt"
        assert info.uncompressed_size == 1024
        assert info.compressed_size == 512
        assert info.is_dir is False

    def test_mtime_conversion(self, sample_zipinfo):
        info = ArchiveMemberInfo.from_zipinfo(sample_zipinfo)
        expected_dt = datetime(2024, 1, 15, 10, 30, 0)
        expected_ts = expected_dt.timestamp()
        assert info.mtime == expected_ts

    def test_mode_from_external_attr(self, sample_zipinfo):
        info = ArchiveMemberInfo.from_zipinfo(sample_zipinfo)
        assert info.mode == 0o644

    def test_mode_is_none_when_no_perms(self):
        zi = zipfile.ZipInfo("file.txt")
        zi.external_attr = 0
        zi.file_size = 100
        zi.compress_size = 50
        info = ArchiveMemberInfo.from_zipinfo(zi)
        assert info.mode is None

    def test_is_dir_for_directory(self, sample_zipinfo_dir):
        info = ArchiveMemberInfo.from_zipinfo(sample_zipinfo_dir)
        assert info.is_dir is True

    def test_raw_is_zipinfo(self, sample_zipinfo):
        info = ArchiveMemberInfo.from_zipinfo(sample_zipinfo)
        assert isinstance(info.raw, zipfile.ZipInfo)
        assert info.raw is sample_zipinfo


class TestArchiveMemberInfoFromTarinfo:
    def test_basic_fields(self, sample_tarinfo):
        info = ArchiveMemberInfo.from_tarinfo(sample_tarinfo)
        assert info.name == "test/file.txt"
        assert info.uncompressed_size == 2048
        assert info.is_dir is False

    def test_compressed_size_is_none(self, sample_tarinfo):
        info = ArchiveMemberInfo.from_tarinfo(sample_tarinfo)
        assert info.compressed_size is None

    def test_mtime_preserved(self, sample_tarinfo):
        info = ArchiveMemberInfo.from_tarinfo(sample_tarinfo)
        assert info.mtime == 1705312200.0

    def test_mode_preserved(self, sample_tarinfo):
        info = ArchiveMemberInfo.from_tarinfo(sample_tarinfo)
        assert info.mode == 0o644

    def test_is_dir_for_directory(self, sample_tarinfo_dir):
        info = ArchiveMemberInfo.from_tarinfo(sample_tarinfo_dir)
        assert info.is_dir is True

    def test_raw_is_tarinfo(self, sample_tarinfo):
        info = ArchiveMemberInfo.from_tarinfo(sample_tarinfo)
        assert isinstance(info.raw, tarfile.TarInfo)
        assert info.raw is sample_tarinfo

    def test_mtime_defaults_to_zero_when_none(self):
        ti = tarfile.TarInfo(name="file.txt")
        ti.size = 100
        object.__setattr__(ti, "mtime", None)
        info = ArchiveMemberInfo.from_tarinfo(ti)
        assert info.mtime == 0.0


class TestArchiveMemberInfoFromRarinfo:
    def test_basic_fields(self):
        import rarfile

        ri = rarfile.RarInfo()
        ri.filename = "test/file.txt"
        ri.file_size = 4096
        ri.compress_size = 2048
        ri.mode = 0o644

        expected_dt = datetime(2024, 6, 1, 12, 0, 0)
        ri.mtime = expected_dt.replace(tzinfo=timezone.utc)
        info = ArchiveMemberInfo.from_rarinfo(ri)

        assert info.name == "test/file.txt"
        assert info.uncompressed_size == 4096
        assert info.compressed_size == 2048
        assert info.is_dir is False

    def test_mtime_from_datetime_object(self):
        import rarfile

        ri = rarfile.RarInfo()
        ri.filename = "file.txt"
        ri.file_size = 100
        ri.compress_size = 50
        ri.mtime = datetime(2024, 3, 1, 8, 0, 0, tzinfo=timezone.utc)
        info = ArchiveMemberInfo.from_rarinfo(ri)
        assert (
            info.mtime == datetime(2024, 3, 1, 8, 0, 0, tzinfo=timezone.utc).timestamp()
        )

    def test_mtime_from_date_time_tuple(self):
        import rarfile

        ri = rarfile.RarInfo()
        ri.filename = "file.txt"
        ri.file_size = 100
        ri.compress_size = 50
        ri.mtime = None
        ri.date_time = (2024, 3, 1, 8, 0, 0)
        info = ArchiveMemberInfo.from_rarinfo(ri)
        expected_dt = datetime(2024, 3, 1, 8, 0, 0)
        expected_ts = expected_dt.timestamp()
        assert info.mtime == expected_ts

    def test_mtime_defaults_to_zero_when_none(self):
        import rarfile

        ri = rarfile.RarInfo()
        ri.filename = "file.txt"
        ri.file_size = 100
        ri.compress_size = 50
        ri.mtime = None
        ri.date_time = None
        info = ArchiveMemberInfo.from_rarinfo(ri)
        assert info.mtime == 0.0

    def test_is_dir(self):
        import rarfile

        ri = rarfile.RarInfo()
        ri.filename = "dir/"
        ri.file_size = 0
        ri.compress_size = 0
        ri.mtime = None
        ri.date_time = (2024, 1, 1, 0, 0, 0)
        ri.host_os = 3
        ri.mode = 0o40755
        info = ArchiveMemberInfo.from_rarinfo(ri)
        assert info.raw.filename == "dir/"
        assert info.raw.mode == 0o40755

    def test_raw_is_rarinfo(self):
        import rarfile

        ri = rarfile.RarInfo()
        ri.filename = "file.txt"
        ri.file_size = 100
        ri.compress_size = 50
        ri.mtime = None
        ri.date_time = (2024, 1, 1, 0, 0, 0)
        info = ArchiveMemberInfo.from_rarinfo(ri)
        assert isinstance(info.raw, rarfile.RarInfo)


class TestArchiveMemberImmutability:
    def test_frozen_dataclass(self, sample_zipinfo):
        info = ArchiveMemberInfo.from_zipinfo(sample_zipinfo)
        with pytest.raises(Exception):
            info.name = "modified.txt"

    def test_replace_creates_new_instance(self, sample_zipinfo):
        info = ArchiveMemberInfo.from_zipinfo(sample_zipinfo)
        modified = replace(info, name="new_name.txt")
        assert modified.name == "new_name.txt"
        assert info.name == "test/file.txt"
