"""Start and stop only the Photostudio processes recorded by this launcher."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path


def _process_snapshot(pid: int) -> dict | None:
    if os.name != "nt":
        raise RuntimeError("Owned-process inspection is supported on Windows only.")
    command = (
        "$process = Get-CimInstance -ClassName Win32_Process "
        "-Filter ('ProcessId = ' + $env:VFS_PROCESS_ID); "
        "if ($process) { [ordered]@{ "
        "executable = $process.ExecutablePath; "
        "command_line = $process.CommandLine; "
        "creation_time = [Int64]$process.CreationDate.ToFileTimeUtc() "
        "} | ConvertTo-Json -Compress }"
    )
    environment = os.environ.copy()
    environment["VFS_PROCESS_ID"] = str(pid)
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
        capture_output=True,
        check=True,
        text=True,
        env=environment,
    )
    if not result.stdout.strip():
        return None
    return json.loads(result.stdout)


def _record_matches(record: dict, snapshot: dict | None) -> bool:
    if snapshot is None:
        return False
    expected_executable = os.path.normcase(os.path.abspath(record["executable"]))
    actual_executable = os.path.normcase(os.path.abspath(snapshot.get("executable") or ""))
    command_line = (snapshot.get("command_line") or "").casefold()
    return (
        actual_executable == expected_executable
        and int(snapshot["creation_time"]) == int(record["creation_time"])
        and all(marker.casefold() in command_line for marker in record["match"])
    )


def _record_path(pid_dir: Path, service: str) -> Path:
    return pid_dir / f"{service}.json"


def start_service(service: str, pid_dir: Path, log_dir: Path, cwd: Path,
                  match: list[str], argv: list[str]) -> None:
    if os.name != "nt":
        raise RuntimeError("The service launcher is Windows-only.")
    if not argv:
        raise ValueError("Provide the executable and arguments to launch.")
    if not match:
        raise ValueError("Provide command-line markers so the process can be verified before stopping it.")
    pid_dir.mkdir(parents=True, exist_ok=True)
    log_dir.mkdir(parents=True, exist_ok=True)
    record_path = _record_path(pid_dir, service)

    if record_path.exists():
        old_record = json.loads(record_path.read_text(encoding="utf-8"))
        if _record_matches(old_record, _process_snapshot(int(old_record["pid"]))):
            print(f"{service} is already running under this launcher (PID {old_record['pid']}).")
            return
        record_path.unlink()

    executable = os.path.abspath(argv[0])
    log_path = log_dir / f"{service}.log"
    creation_flags = (
        subprocess.CREATE_NO_WINDOW
        | subprocess.CREATE_NEW_PROCESS_GROUP
        | subprocess.BELOW_NORMAL_PRIORITY_CLASS
    )
    with log_path.open("ab") as log_file:
        process = subprocess.Popen(
            argv,
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            creationflags=creation_flags,
        )

    time.sleep(0.5)
    if process.poll() is not None:
        raise RuntimeError(f"{service} exited during startup. Check its log: {log_path}")

    snapshot = _process_snapshot(process.pid)
    if snapshot is None:
        process.terminate()
        process.wait(timeout=5)
        raise RuntimeError(f"Could not inspect the newly started {service} process.")
    record = {
        "pid": process.pid,
        "executable": executable,
        "match": match,
        "creation_time": snapshot["creation_time"],
    }
    temporary_path = record_path.with_suffix(".tmp")
    temporary_path.write_text(json.dumps(record, indent=2), encoding="utf-8")
    os.replace(temporary_path, record_path)
    print(f"Started {service} (PID {process.pid}); log: {log_path}")


def stop_service(service: str, pid_dir: Path) -> None:
    record_path = _record_path(pid_dir, service)
    if not record_path.exists():
        print(f"{service} was not started by this launcher; leaving it untouched.")
        return

    record = json.loads(record_path.read_text(encoding="utf-8"))
    snapshot = _process_snapshot(int(record["pid"]))
    if snapshot is None:
        record_path.unlink()
        print(f"{service} is already stopped.")
        return
    if not _record_matches(record, snapshot):
        record_path.unlink()
        print(f"{service} PID no longer matches its launch record; leaving the process untouched.")
        return
    if os.name != "nt":
        raise RuntimeError("The service launcher is Windows-only.")

    command = """
$processes = @(Get-CimInstance -ClassName Win32_Process)
$root = $processes | Where-Object { $_.ProcessId -eq [int]$env:VFS_PROCESS_ID }
if (-not $root) { throw 'Process is no longer running.' }
$markers = ConvertFrom-Json $env:VFS_MATCH_MARKERS
$allMarkersPresent = $true
foreach ($marker in $markers) {
    if ($root.CommandLine.IndexOf($marker, [StringComparison]::OrdinalIgnoreCase) -lt 0) {
        $allMarkersPresent = $false
    }
}
if ($root.ExecutablePath -ine $env:VFS_EXPECTED_EXECUTABLE -or
    [Int64]$root.CreationDate.ToFileTimeUtc() -ne [Int64]$env:VFS_PROCESS_CREATED -or
    -not $allMarkersPresent) {
    throw 'Process identity changed; refusing to stop it.'
}
$descendants = [System.Collections.Generic.List[object]]::new()
$frontier = @([int]$root.ProcessId)
$depth = 1
while ($frontier.Count -gt 0) {
    $next = @()
    foreach ($parentId in $frontier) {
        foreach ($child in $processes | Where-Object { $_.ParentProcessId -eq $parentId }) {
            if ($child.ProcessId -ne $PID) {
                $descendants.Add([pscustomobject]@{ Process = $child; Depth = $depth })
            }
            $next += [int]$child.ProcessId
        }
    }
    $frontier = $next
    $depth += 1
}
foreach ($item in $descendants | Sort-Object -Property Depth -Descending) {
    Stop-Process -Id $item.Process.ProcessId -Force -ErrorAction SilentlyContinue
}
Stop-Process -Id $root.ProcessId -Force
"""
    environment = os.environ.copy()
    environment["VFS_PROCESS_ID"] = str(record["pid"])
    environment["VFS_EXPECTED_EXECUTABLE"] = record["executable"]
    environment["VFS_PROCESS_CREATED"] = str(record["creation_time"])
    environment["VFS_MATCH_MARKERS"] = json.dumps(record["match"])
    subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
        capture_output=True,
        check=True,
        text=True,
        env=environment,
    )
    record_path.unlink(missing_ok=True)
    print(f"Stopped {service} (PID {record['pid']}).")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("start", "stop"))
    parser.add_argument("service", choices=("comfy", "photostudio"))
    parser.add_argument("--pid-dir", required=True, type=Path)
    parser.add_argument("--log-dir", type=Path, default=Path.cwd())
    parser.add_argument("--cwd", type=Path, default=Path.cwd())
    parser.add_argument("--match", action="append", default=[])
    arguments = sys.argv[1:]
    if "--" in arguments:
        separator = arguments.index("--")
        parser_arguments, argv = arguments[:separator], arguments[separator + 1:]
    else:
        parser_arguments, argv = arguments, []
    args = parser.parse_args(parser_arguments)

    if args.action == "stop":
        stop_service(args.service, args.pid_dir)
        return

    start_service(args.service, args.pid_dir, args.log_dir, args.cwd, args.match, argv)


if __name__ == "__main__":
    main()
