"""Copy only ml outside its repository, install clean dependencies, verify it."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import traceback

ROOT = Path(__file__).resolve().parents[1]
EXCLUDED = {".venv", ".git", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"}


def main():
    report_dir = ROOT / "reports" / "packaging"
    report_dir.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix="prime-checkup-isolated-"))
    copied = temporary / "ml"
    report = {"source": str(ROOT), "temporary_parent": str(temporary), "copy": str(copied),
              "copied_only_ml": True, "excluded": sorted(EXCLUDED), "commands": [],
              "source_environment_copied": False, "pythonpath_removed": True}
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    env.pop("PYTHONHOME", None)
    env.update(PYTHONNOUSERSITE="1", PYTHONIOENCODING="utf-8")
    try:
        if temporary.is_relative_to(ROOT.parent):
            raise RuntimeError("Temporary copy must be outside the parent project")
        for folder, dirs, files in os.walk(ROOT):
            dirs[:] = [name for name in dirs if name not in EXCLUDED]
            for name in dirs + files:
                path = Path(folder) / name
                if path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction()):
                    raise RuntimeError(f"Links/junctions cannot be packaged: {path}")
        shutil.copytree(ROOT, copied, ignore=shutil.ignore_patterns(*EXCLUDED, "*.pyc", "*.pyo", "*.tmp", "*.temp"))
        relative_paths = [p.relative_to(ROOT) for base in ("prime_checkup", "tests", "tools", "docs", "reference")
                          for p in (ROOT / base).rglob("*") if p.is_file() and not any(part in EXCLUDED for part in p.parts)]
        report["copy_hashes"] = {p.as_posix(): {"source": hashlib.sha256((ROOT / p).read_bytes()).hexdigest(),
                                              "copy": hashlib.sha256((copied / p).read_bytes()).hexdigest()}
                                 for p in sorted(relative_paths)}
        assert all(row["source"] == row["copy"] for row in report["copy_hashes"].values())
        python = copied / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        commands = [
            ("venv", [getattr(sys, "_base_executable", sys.executable), "-m", "venv", str(copied / ".venv")]),
            ("install", [str(python), "-m", "pip", "install", "--disable-pip-version-check", "--timeout", "20", "--retries", "1", "-r", "requirements-dev.txt"]),
            ("verify", [str(python), "-s", "-X", "utf8", "-m", "tools.verify_package", "--label", "isolated"]),
        ]
        for name, command in commands:
            log_path = report_dir / f"isolation_{name}.log"
            with log_path.open("w", encoding="utf-8") as log:
                result = subprocess.run(command, cwd=copied, env=env, stdout=log, stderr=subprocess.STDOUT)
            report["commands"].append({"name": name, "command": command, "cwd": str(copied), "returncode": result.returncode,
                                        "log": log_path.relative_to(ROOT).as_posix()})
            print(name, result.returncode, flush=True)
            if result.returncode:
                raise RuntimeError(f"{name} failed; see {log_path}")
        report["pyvenv_config"] = (copied / ".venv" / "pyvenv.cfg").read_text(encoding="utf-8")
        report["copied_reports"] = []
        for path in sorted((copied / "reports" / "packaging").glob("*isolated*")):
            if path.is_file():
                shutil.copy2(path, report_dir / path.name)
                report["copied_reports"].append(path.name)
        report["verification"] = json.loads((report_dir / "verification_isolated.json").read_text(encoding="utf-8"))["summary"]
        report["verdict"] = "PASS"
    except Exception:
        report["verdict"] = "FAIL"
        report["traceback"] = traceback.format_exc()
    (report_dir / "isolation.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(report["verdict"], str(copied))
    return 0 if report["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
