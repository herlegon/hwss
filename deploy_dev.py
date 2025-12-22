import os
from pathlib import Path
from pprint import pprint
import shutil
import subprocess
import sys

from hinstall import g_backend_dirs

d_backend_dirs = g_backend_dirs
d_python_dir = g_backend_dirs.python_exe.parent.parent
d_modules_dir = d_python_dir / "modules"
d_hwss = d_modules_dir / "hwss"
d_hinstall = d_modules_dir / "hinstall"

s_bootstrap_dir = Path(__file__).resolve().parent / "bootstrap"
s_hwss = Path(__file__).resolve().parent.parent / "hwss" / "hwss"
s_hinstall = Path(__file__).resolve().parent.parent / "hinstall" / "hinstall"

# Helper functions
def remove_pyd_files(directory: Path):
    if directory.exists():
        for pyd_file in directory.glob("*.pyd"):
            pyd_file.unlink()
            print(f"    Removed: {pyd_file.name}")


def remove_bootstrap_extensions(directory: Path):
    """Remove .pyd/.so files in d_python that start with 'bootstrap'"""
    if not directory.exists():
        return

    # Match both .pyd and .so files starting with 'bootstrap'
    for ext_file in directory.glob("bootstrap*.pyd"):
        if ext_file.is_symlink():
            ext_file.unlink()
            print(f"    Unlinked symlink: {ext_file.name}")
        else:
            ext_file.unlink()
            print(f"    Removed: {ext_file.name}")

    for ext_file in directory.glob("bootstrap*.so"):
        if ext_file.is_symlink():
            ext_file.unlink()
            print(f"    Unlinked symlink: {ext_file.name}")
        else:
            ext_file.unlink()
            print(f"    Removed: {ext_file.name}")


def remove_directory_or_symlink(path: Path):
    """Remove directory (and contents) or unlink if symlink"""
    if not path.exists() and not path.is_symlink():
        return

    if path.is_symlink():
        path.unlink()
        print(f"    Unlinked symlink: {path.name}")
    else:
        print(f"    WARNING: Removing directory and its contents: {path}")
        shutil.rmtree(path)
        print(f"    Removed: {path.name}")


def create_symlinks():
    """Create symlinks for hwss, hinstall, and bootstrap extensions"""
    print("Creating symlinks...")

    # Create symlink for hwss
    print(f"    {d_hwss} -> {s_hwss}")
    if d_hwss.exists() or d_hwss.is_symlink():
        remove_directory_or_symlink(d_hwss)
    d_hwss.symlink_to(s_hwss)

    # Create symlink for hinstall
    if d_hinstall.exists() or d_hinstall.is_symlink():
        remove_directory_or_symlink(d_hinstall)
    d_hinstall.symlink_to(s_hinstall)
    print(f"    Created symlink: {d_hinstall.name} -> {s_hinstall}")

    # Create symlinks for bootstrap extensions
    for src_file in s_bootstrap_dir.glob("bootstrap*.pyd"):
        dst_file = d_python_dir / src_file.name
        if dst_file.exists() or dst_file.is_symlink():
            dst_file.unlink()
        dst_file.symlink_to(src_file)
        print(f"    Created symlink: {dst_file.name} -> {src_file.name}")

    for src_file in s_bootstrap_dir.glob("bootstrap*.so"):
        dst_file = d_python_dir / src_file.name
        if dst_file.exists() or dst_file.is_symlink():
            dst_file.unlink()
        dst_file.symlink_to(src_file)
        print(f"    Created symlink: {dst_file.name} -> {src_file.name}")


def copy_files():
    """Copy source files to destination directories"""
    print("Copying files...")

    # Copy hwss
    if d_hwss.exists() or d_hwss.is_symlink():
        remove_directory_or_symlink(d_hwss)
    shutil.copytree(s_hwss, d_hwss)
    print(f"    Copied: {s_hwss} -> {d_hwss}")

    # Copy hinstall
    if d_hinstall.exists() or d_hinstall.is_symlink():
        remove_directory_or_symlink(d_hinstall)
    shutil.copytree(s_hinstall, d_hinstall)
    print(f"    Copied: {s_hinstall} -> {d_hinstall}")

    # Copy bootstrap extensions
    for src_file in s_bootstrap_dir.glob("bootstrap*.pyd"):
        dst_file = d_python_dir / src_file.name
        if dst_file.exists() or dst_file.is_symlink():
            dst_file.unlink()
        shutil.copy2(src_file, dst_file)
        print(f"    Copied: {src_file.name} -> {dst_file.name}")

    for src_file in s_bootstrap_dir.glob("bootstrap*.so"):
        dst_file = d_python_dir / src_file.name
        if dst_file.exists() or dst_file.is_symlink():
            dst_file.unlink()
        shutil.copy2(src_file, dst_file)
        print(f"    Copied: {src_file.name} -> {dst_file.name}")



if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Setup Python environment in dev or prod mode"
    )
    parser.add_argument(
        "--dev",
        action="store_true",
        default=True,
        help="Setup mode: creates symlinks (default)"
    )
    parser.add_argument(
        "--prod",
        action="store_true",
        help="Setup mode: copies files"
    )

    args = parser.parse_args()

    # prod takes priority if both are specified, otherwise default to dev
    mode = "prod" if args.prod else "dev"

    print("Cleaning up bootstrap extensions...")
    remove_bootstrap_extensions(d_python_dir)

    print("\nCleaning up hwss...")
    remove_directory_or_symlink(d_hwss)

    print("\nCleaning up hinstall...")
    remove_directory_or_symlink(d_hinstall)

    print(f"\n{'=' * 50}")
    print(f"Setting up {mode.upper()} mode")
    print(f"{'=' * 50}\n")

    d_modules_dir.mkdir(exist_ok=True)
    if mode == "dev":
        create_symlinks()
    elif mode == "prod":
        copy_files()

    print(f"\n✓ {mode.upper()} mode setup complete!")
