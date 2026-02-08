from __future__ import annotations

import os
import sys

from sx.paths import PathResolver


def test_linux_paths():
    config = {
        'path_style': 'linux',
        'vault': '/mnt/t/Vault',
        'data_dir': 'data'
    }
    resolver = PathResolver(config)
    path = resolver.resolve_absolute('Favorites/video.mp4')
    assert path == '/mnt/t/Vault/data/Favorites/video.mp4'


def test_windows_paths():
    config = {
        'path_style': 'windows',
        'vault': '/mnt/t/Vault',
        'vault_windows': 'T:\\Vault',
        'data_dir': 'data'
    }
    resolver = PathResolver(config)
    path = resolver.resolve_absolute('Favorites/video.mp4')
    assert path == 'T:\\Vault\\data\\Favorites\\video.mp4'


def test_os_absolute_and_exists(tmp_path):
    # Generate Windows-style protocol paths, but check file existence on this OS.
    vault = tmp_path / "Vault"
    (vault / "data" / "Favorites").mkdir(parents=True)
    media_path = vault / "data" / "Favorites" / "video.mp4"
    media_path.write_bytes(b"x")

    config = {
        'path_style': 'windows',
        'vault': str(vault),
        'vault_windows': 'T:\\Vault',
        'data_dir': 'data'
    }
    resolver = PathResolver(config)

    assert resolver.resolve_absolute('Favorites/video.mp4') == 'T:\\Vault\\data\\Favorites\\video.mp4'
    assert resolver.resolve_os_absolute('Favorites/video.mp4') == str(media_path)
    assert resolver.exists('Favorites/video.mp4') is True
    assert resolver.exists('Favorites/missing.mp4') is False


def test_path_cleaning():
    config = {
        'path_style': 'windows',
        'vault_windows': 'T:\\Vault\\',
        'data_dir': '\\data\\'
    }
    resolver = PathResolver(config)
    path = resolver.resolve_absolute('/Favorites/video.mp4/')
    assert path == 'T:\\Vault\\data\\Favorites\\video.mp4'


def test_fallback_logic():
    config = {
        'path_style': 'linux',
        'vault': '/mnt/t/Vault',
        'vault_linux': None,  # Simulated missing env var
        'data_dir': 'data'
    }
    resolver = PathResolver(config)
    assert resolver.vault_root == '/mnt/t/Vault'


if __name__ == "__main__":
    # Allow quick execution without pytest from any working directory.
    sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

    # Allow quick execution without pytest.
    test_linux_paths()
    test_windows_paths()
    test_path_cleaning()
    test_fallback_logic()
    print("All Path Mapping Tests Passed!")
