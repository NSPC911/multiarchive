import gzip
import tarfile
import zipfile
from io import BytesIO
from pathlib import Path

import pytest

from multiarchive._archive import Archive, ArchiveMemberInfo, BadArchiveError


@pytest.fixture
def tmp_path(tmp_path):
    return tmp_path


@pytest.fixture
def sample_file_content():
    return {
        "file1.txt": b"Hello, World!",
        "file2.txt": b"Test content",
        "subdir/file3.txt": b"Nested file content",
    }


@pytest.fixture
def zip_archive(tmp_path, sample_file_content):
    zip_path = tmp_path / "test.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        for name, content in sample_file_content.items():
            zf.writestr(name, content)
    return zip_path


@pytest.fixture
def zip_with_dir(tmp_path):
    zip_path = tmp_path / "test_with_dir.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zi = zipfile.ZipInfo("mydir/")
        zf.writestr(zi, "")
        zf.writestr("file.txt", b"content")
    return zip_path


@pytest.fixture
def tar_archive(tmp_path, sample_file_content):
    tar_path = tmp_path / "test.tar"
    with tarfile.open(tar_path, "w") as tf:
        for name, content in sample_file_content.items():
            data = content
            info = tarfile.TarInfo(name=name)
            info.size = len(data)
            tf.addfile(info, BytesIO(data))
    return tar_path


@pytest.fixture
def tar_gz_archive(tmp_path, sample_file_content):
    tar_path = tmp_path / "test.tar.gz"
    with tarfile.open(tar_path, "w:gz") as tf:
        for name, content in sample_file_content.items():
            data = content
            info = tarfile.TarInfo(name=name)
            info.size = len(data)
            tf.addfile(info, BytesIO(data))
    return tar_path


@pytest.fixture
def tar_with_dir(tmp_path):
    tar_path = tmp_path / "test_with_dir.tar"
    with tarfile.open(tar_path, "w") as tf:
        dir_info = tarfile.TarInfo(name="mydir/")
        dir_info.type = tarfile.DIRTYPE
        tf.addfile(dir_info)
        data = b"content"
        info = tarfile.TarInfo(name="file.txt")
        info.size = len(data)
        tf.addfile(info, BytesIO(data))
    return tar_path


@pytest.fixture
def rar_archive(tmp_path, sample_file_content):
    rar_path = tmp_path / "test.rar"
    import shutil

    src_dir = tmp_path / "rar_src"
    src_dir.mkdir()
    for name, content in sample_file_content.items():
        full_path = src_dir / name
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_bytes(content)
    shutil.make_archive(str(tmp_path / "test"), "zip", src_dir)
    temp_zip = tmp_path / "test.zip"
    temp_zip.rename(rar_path)
    rar_path.unlink(missing_ok=True)
    import rarfile

    if not hasattr(rarfile, "UNRAR_TOOL"):
        pytest.skip("rarfile unrar tool not available")
    pytest.skip("RAR creation requires external tools, skipping")


class TestArchiveInitialization:
    def test_context_manager_read_zip(self, zip_archive):
        with Archive(zip_archive) as archive:
            assert archive._archive is not None
            assert archive._archive_type == "zip"

    def test_context_manager_read_tar(self, tar_archive):
        with Archive(tar_archive) as archive:
            assert archive._archive is not None
            assert archive._archive_type == "tar"

    def test_context_manager_read_tar_gz(self, tar_gz_archive):
        with Archive(tar_gz_archive) as archive:
            assert archive._archive is not None
            assert archive._archive_type == "tar"

    def test_open_archive_factory_method(self, zip_archive):
        archive = Archive.open_archive(zip_archive)
        try:
            assert archive._archive is not None
            assert archive._archive_type == "zip"
        finally:
            archive.close()

    def test_open_archive_with_compression_level(self, tmp_path):
        zip_path = tmp_path / "test.zip"
        archive = Archive.open_archive(zip_path, mode="w", compression_level=5)
        try:
            assert archive._archive is not None
        finally:
            archive.close()

    def test_open_archive_closes_properly(self, zip_archive):
        archive = Archive.open_archive(zip_archive)
        assert archive._archive is not None
        archive.close()
        assert archive._archive is None

    def test_file_not_found(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            with Archive(tmp_path / "nonexistent.zip"):
                pass

    def test_bad_archive(self, tmp_path):
        bad_file = tmp_path / "bad.dat"
        bad_file.write_bytes(b"not an archive")
        with pytest.raises(ValueError, match="not a valid ZIP, RAR, or TAR archive"):
            with Archive(bad_file):
                pass

    def test_unsupported_write_mode_rar(self, tmp_path):
        with pytest.raises(
            ValueError, match="RAR files can only be opened in read mode"
        ):
            Archive.open_archive(tmp_path / "test.rar", mode="w")


class TestZipArchive:
    def test_namelist(self, zip_archive):
        with Archive(zip_archive) as archive:
            names = archive.namelist()
            assert "file1.txt" in names
            assert "file2.txt" in names
            assert "subdir/file3.txt" in names

    def test_members_property(self, zip_archive):
        with Archive(zip_archive) as archive:
            assert archive.members == archive.namelist()

    def test_infolist(self, zip_archive):
        with Archive(zip_archive) as archive:
            infos = archive.infolist()
            assert len(infos) == 3
            assert all(isinstance(info, ArchiveMemberInfo) for info in infos)

    def test_infolist_contains_unified_data(self, zip_archive):
        with Archive(zip_archive) as archive:
            infos = archive.infolist()
            file_info = next(i for i in infos if i.name == "file1.txt")
            assert file_info.uncompressed_size == 13
            assert file_info.compressed_size is not None
            assert file_info.is_dir is False
            assert file_info.mtime > 0
            assert isinstance(file_info.raw, zipfile.ZipInfo)

    def test_extract_single_file(self, zip_archive, tmp_path):
        with Archive(zip_archive) as archive:
            extract_path = tmp_path / "extracted"
            extract_path.mkdir()
            result = archive.extract("file1.txt", extract_path)
            assert Path(result).exists()
            assert Path(result).read_bytes() == b"Hello, World!"

    def test_open_member(self, zip_archive):
        with Archive(zip_archive) as archive:
            f = archive.open("file1.txt")
            assert f is not None
            content = f.read()
            f.close()
        assert content == b"Hello, World!"

    def test_read_member(self, zip_archive):
        with Archive(zip_archive) as archive:
            f = archive.open("file1.txt")
            assert f is not None
            content = f.read()
            f.close()
        assert content == b"Hello, World!"

    def test_is_dir_for_file(self, zip_archive):
        with Archive(zip_archive) as archive:
            assert archive.is_dir("file1.txt") is False

    def test_is_dir_for_directory(self, zip_with_dir):
        with Archive(zip_with_dir) as archive:
            assert archive.is_dir("mydir/") is True

    def test_is_file_for_file(self, zip_archive):
        with Archive(zip_archive) as archive:
            assert archive.is_file("file1.txt") is True

    def test_is_file_for_directory(self, zip_with_dir):
        with Archive(zip_with_dir) as archive:
            assert archive.is_file("mydir/") is False

    def test_comment_get_set(self, zip_archive):
        with Archive(zip_archive, mode="a") as archive:
            assert archive.comment == b""
            archive.comment = b"My archive comment"
        with Archive(zip_archive) as archive:
            assert archive.comment == b"My archive comment"

    def test_comment_non_zip(self, tar_archive):
        with Archive(tar_archive) as archive:
            assert archive.comment == b""

    def test_comment_set_on_non_zip(self, tar_archive):
        with Archive(tar_archive, mode="a") as archive:
            with pytest.raises(
                ValueError, match="Archive comment is only supported for ZIP"
            ):
                archive.comment = b"test"


class TestTarArchive:
    def test_namelist(self, tar_archive):
        with Archive(tar_archive) as archive:
            names = archive.namelist()
            assert "file1.txt" in names
            assert "file2.txt" in names
            assert "subdir/file3.txt" in names

    def test_infolist_returns_unified(self, tar_archive):
        with Archive(tar_archive) as archive:
            infos = archive.infolist()
            assert len(infos) == 3
            assert all(isinstance(info, ArchiveMemberInfo) for info in infos)

    def test_infolist_compressed_size_none(self, tar_archive):
        with Archive(tar_archive) as archive:
            infos = archive.infolist()
            for info in infos:
                assert info.compressed_size is None

    def test_extract_single_file(self, tar_archive, tmp_path):
        with Archive(tar_archive) as archive:
            extract_path = tmp_path / "extracted"
            extract_path.mkdir()
            result = archive.extract("file1.txt", extract_path)
            assert Path(result).exists()
            assert Path(result).read_bytes() == b"Hello, World!"

    def test_open_member(self, tar_archive):
        with Archive(tar_archive) as archive:
            f = archive.open("file1.txt")
            assert f is not None
            content = f.read()
            f.close()
        assert content == b"Hello, World!"

    def test_read_member(self, tar_archive):
        with Archive(tar_archive) as archive:
            f = archive.open("file1.txt")
            assert f is not None
            content = f.read()
            f.close()
        assert content == b"Hello, World!"

    def test_is_dir_for_file(self, tar_archive):
        with Archive(tar_archive) as archive:
            assert archive.is_dir("file1.txt") is False

    def test_is_dir_for_directory(self, tar_with_dir):
        with Archive(tar_with_dir) as archive:
            assert archive.is_dir("mydir/") is True

    def test_is_file_for_file(self, tar_archive):
        with Archive(tar_archive) as archive:
            assert archive.is_file("file1.txt") is True

    def test_is_file_for_directory(self, tar_with_dir):
        with Archive(tar_with_dir) as archive:
            assert archive.is_file("mydir/") is False

    def test_tar_gz_detected(self, tar_gz_archive):
        with Archive(tar_gz_archive) as archive:
            assert archive._archive_type == "tar"
            names = archive.namelist()
            assert "file1.txt" in names


class TestArchiveProperties:
    def test_size_zip(self, zip_archive):
        with Archive(zip_archive) as archive:
            assert archive.size > 0
            assert archive.size == 13 + 12 + 19

    def test_size_tar(self, tar_archive):
        with Archive(tar_archive) as archive:
            assert archive.size > 0
            assert archive.size == 13 + 12 + 19

    def test_len_zip(self, zip_archive):
        with Archive(zip_archive) as archive:
            assert len(archive) == 3

    def test_len_tar(self, tar_archive):
        with Archive(tar_archive) as archive:
            assert len(archive) == 3


class TestDunderMethods:
    def test_iter(self, zip_archive):
        with Archive(zip_archive) as archive:
            names = list(archive)
            assert "file1.txt" in names
            assert "file2.txt" in names

    def test_contains_true(self, zip_archive):
        with Archive(zip_archive) as archive:
            assert "file1.txt" in archive

    def test_contains_false(self, zip_archive):
        with Archive(zip_archive) as archive:
            assert "nonexistent.txt" not in archive

    def test_len(self, zip_archive):
        with Archive(zip_archive) as archive:
            assert len(archive) == 3


class TestClose:
    def test_close_sets_archive_none(self, zip_archive):
        archive = Archive.open_archive(zip_archive)
        archive.close()
        assert archive._archive is None

    def test_close_idempotent(self, zip_archive):
        archive = Archive.open_archive(zip_archive)
        archive.close()
        archive.close()
        assert archive._archive is None

    def test_context_manager_closes(self, zip_archive):
        with Archive(zip_archive) as archive:
            pass
        assert archive._archive is not None
        assert archive._archive.fp is None


class TestRuntimeErrorCases:
    def test_namelist_without_open(self, tmp_path):
        archive = Archive(tmp_path / "test.zip")
        with pytest.raises(RuntimeError, match="Archive not opened"):
            archive.namelist()

    def test_infolist_without_open(self, tmp_path):
        archive = Archive(tmp_path / "test.zip")
        with pytest.raises(RuntimeError, match="Archive not opened"):
            archive.infolist()

    def test_is_dir_without_open(self, tmp_path):
        archive = Archive(tmp_path / "test.zip")
        with pytest.raises(RuntimeError, match="Archive not opened"):
            archive.is_dir("file.txt")

    def test_is_file_without_open(self, tmp_path):
        archive = Archive(tmp_path / "test.zip")
        with pytest.raises(RuntimeError, match="Archive not opened"):
            archive.is_file("file.txt")

    def test_size_without_open(self, tmp_path):
        archive = Archive(tmp_path / "test.zip")
        with pytest.raises(RuntimeError, match="Archive not opened"):
            _ = archive.size

    def test_comment_without_open(self, tmp_path):
        archive = Archive(tmp_path / "test.zip")
        with pytest.raises(RuntimeError, match="Archive not opened"):
            _ = archive.comment


class TestWriteMode:
    def test_create_zip(self, tmp_path):
        zip_path = tmp_path / "new.zip"
        with Archive(zip_path, mode="w") as archive:
            pass
        assert zip_path.exists()

    def test_create_tar(self, tmp_path):
        tar_path = tmp_path / "new.tar"
        with Archive(tar_path, mode="w") as archive:
            pass
        assert tar_path.exists()

    def test_create_tar_gz(self, tmp_path):
        tar_path = tmp_path / "new.tar.gz"
        with Archive(tar_path, mode="w") as archive:
            pass
        assert tar_path.exists()

    def test_compression_level_zip_invalid(self, tmp_path):
        with pytest.raises(ValueError, match="compression level must be between 0-9"):
            Archive.open_archive(tmp_path / "test.zip", mode="w", compression_level=15)

    def test_compression_level_zip_valid(self, tmp_path):
        archive = Archive.open_archive(
            tmp_path / "test.zip", mode="w", compression_level=5
        )
        try:
            assert archive._archive is not None
        finally:
            archive.close()


class TestBadArchiveError:
    def test_bad_zip(self, tmp_path):
        bad_file = tmp_path / "bad.zip"
        bad_file.write_bytes(b"PK\x03\x04garbage")
        with pytest.raises(ValueError, match="not a valid ZIP, RAR, or TAR archive"):
            with Archive(bad_file):
                pass

    def test_bad_tar(self, tmp_path):
        bad_file = tmp_path / "bad.tar"
        bad_file.write_bytes(b"not a tar file at all")
        with pytest.raises(ValueError, match="not a valid ZIP, RAR, or TAR archive"):
            with Archive(bad_file):
                pass


class TestPasswordProtected:
    def test_password_protected_zip_skipped(self):
        pytest.skip(
            "Creating password-protected ZIP requires external encryption tools"
        )
