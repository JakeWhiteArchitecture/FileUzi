#!/usr/bin/env python3
"""
Minimal Betterbird Flatpak email-compose test.

Run this on Fedora to diagnose why Betterbird isn't opening a compose window.
Each test prints exactly what it's doing so you can see what fails and why.

Usage:
    python test_betterbird_launch.py
"""

import subprocess
import shutil
import os
from pathlib import Path


def banner(msg):
    print(f"\n{'='*60}")
    print(f"  {msg}")
    print(f"{'='*60}")


def run_and_report(description, cmd):
    """Run a command, print its output and return code."""
    print(f"\n--- {description} ---")
    print(f"  Command: {cmd}")
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=10
        )
        print(f"  Return code: {result.returncode}")
        if result.stdout.strip():
            print(f"  stdout: {result.stdout.strip()[:500]}")
        if result.stderr.strip():
            print(f"  stderr: {result.stderr.strip()[:500]}")
        return result.returncode == 0
    except FileNotFoundError:
        print(f"  ERROR: command not found: {cmd[0]}")
        return False
    except subprocess.TimeoutExpired:
        print(f"  ERROR: command timed out after 10s")
        return False
    except Exception as e:
        print(f"  ERROR: {e}")
        return False


def main():
    banner("1. ENVIRONMENT CHECK")

    # Check OS
    print(f"\n  OS: ", end="")
    try:
        os_release = Path("/etc/os-release").read_text()
        for line in os_release.splitlines():
            if line.startswith("PRETTY_NAME="):
                print(line.split("=", 1)[1].strip('"'))
                break
    except Exception:
        print("unknown")

    # Check flatpak is installed
    flatpak_path = shutil.which("flatpak")
    print(f"  flatpak binary: {flatpak_path or 'NOT FOUND'}")

    banner("2. IS BETTERBIRD INSTALLED?")

    # Check Flatpak registry
    run_and_report(
        "flatpak info",
        ["flatpak", "info", "eu.betterbird.Betterbird"]
    )

    # Check export wrapper
    wrapper = Path("/var/lib/flatpak/exports/bin/eu.betterbird.Betterbird")
    print(f"\n  Export wrapper exists: {wrapper.exists()}")
    if wrapper.exists():
        print(f"  Is symlink: {wrapper.is_symlink()}")
        if wrapper.is_symlink():
            print(f"  Symlink target: {os.readlink(wrapper)}")
        print(f"  Is executable: {os.access(wrapper, os.X_OK)}")
        # Show first few bytes to see if it's a shell script
        try:
            with open(wrapper, "r") as f:
                head = f.read(200)
            print(f"  File contents (first 200 chars):\n    {head[:200]}")
        except Exception as e:
            print(f"  Cannot read wrapper: {e}")

    # Check user-local flatpak
    user_wrapper = Path.home() / ".local/share/flatpak/exports/bin/eu.betterbird.Betterbird"
    print(f"\n  User export wrapper exists: {user_wrapper.exists()}")

    banner("3. CHECK FLATPAK PERMISSIONS")

    run_and_report(
        "flatpak permissions (look for filesystem access)",
        ["flatpak", "info", "--show-permissions", "eu.betterbird.Betterbird"]
    )

    banner("4. TEST: Simple compose via 'flatpak run'")

    compose_simple = "to='',subject='FileUzi Test Email'"
    cmd = ["flatpak", "run", "eu.betterbird.Betterbird", "-compose", compose_simple]
    print(f"\n  Launching: {cmd}")
    try:
        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        print(f"  PID: {proc.pid}")
        # Wait briefly for immediate errors
        try:
            stdout, stderr = proc.communicate(timeout=3)
            print(f"  Exited immediately with code: {proc.returncode}")
            if stdout:
                print(f"  stdout: {stdout.decode()[:500]}")
            if stderr:
                print(f"  stderr: {stderr.decode()[:500]}")
        except subprocess.TimeoutExpired:
            print(f"  Process still running after 3s (this is GOOD - Betterbird is starting)")
            print(f"  Check if a compose window appeared in Betterbird.")
    except Exception as e:
        print(f"  LAUNCH FAILED: {e}")

    banner("5. TEST: Compose via export wrapper (if it exists)")

    if wrapper.exists():
        cmd = [str(wrapper), "-compose", compose_simple]
        print(f"\n  Launching: {cmd}")
        try:
            proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE
            )
            print(f"  PID: {proc.pid}")
            try:
                stdout, stderr = proc.communicate(timeout=3)
                print(f"  Exited immediately with code: {proc.returncode}")
                if stdout:
                    print(f"  stdout: {stdout.decode()[:500]}")
                if stderr:
                    print(f"  stderr: {stderr.decode()[:500]}")
            except subprocess.TimeoutExpired:
                print(f"  Process still running after 3s (this is GOOD)")
        except Exception as e:
            print(f"  LAUNCH FAILED: {e}")
    else:
        print("\n  Skipped - no export wrapper found")

    banner("6. TEST: Compose with attachment via 'flatpak run'")

    # Create a tiny temp file to attach
    test_file = Path("/tmp/fileuzi_test_attachment.txt")
    test_file.write_text("This is a test attachment from FileUzi.")

    compose_with_attach = (
        f"to='',"
        f"subject='FileUzi Test With Attachment',"
        f"attachment='file://{test_file}',"
        f"body='Test body',"
        f"format=html"
    )
    cmd = ["flatpak", "run", "eu.betterbird.Betterbird", "-compose", compose_with_attach]
    print(f"\n  Compose string: {compose_with_attach}")
    print(f"  Launching: {cmd}")
    try:
        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        print(f"  PID: {proc.pid}")
        try:
            stdout, stderr = proc.communicate(timeout=3)
            print(f"  Exited immediately with code: {proc.returncode}")
            if stdout:
                print(f"  stdout: {stdout.decode()[:500]}")
            if stderr:
                print(f"  stderr: {stderr.decode()[:500]}")
        except subprocess.TimeoutExpired:
            print(f"  Process still running after 3s (this is GOOD)")
    except Exception as e:
        print(f"  LAUNCH FAILED: {e}")

    banner("7. TEST: xdg-email fallback (if compose flags don't work)")

    xdg_email = shutil.which("xdg-email")
    print(f"\n  xdg-email binary: {xdg_email or 'NOT FOUND'}")
    if xdg_email:
        cmd = [xdg_email, "--subject", "FileUzi xdg-email Test"]
        print(f"  Launching: {cmd}")
        try:
            proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE
            )
            print(f"  PID: {proc.pid}")
            try:
                stdout, stderr = proc.communicate(timeout=5)
                print(f"  Return code: {proc.returncode}")
                if stderr:
                    print(f"  stderr: {stderr.decode()[:500]}")
            except subprocess.TimeoutExpired:
                print(f"  Process still running after 5s (this is GOOD)")
        except Exception as e:
            print(f"  LAUNCH FAILED: {e}")

    banner("DONE")
    print("\nLook for a Betterbird compose window. If tests 4, 5, or 6 show")
    print("'Process still running after 3s' but NO compose window appeared,")
    print("Betterbird may be receiving the command but ignoring -compose.")
    print("\nIf Betterbird was already running, it may have opened the compose")
    print("window in the existing instance and the test process exited quickly.")
    print()


if __name__ == "__main__":
    main()
