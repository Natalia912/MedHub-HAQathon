"""Reproduce packaged regression, 48 scenarios, live HTTP and router mounting."""
import argparse
from datetime import datetime, timezone
import hashlib
import importlib
from importlib.metadata import distributions
import json
import os
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--label", choices=("local", "isolated"), default="local")
    args = parser.parse_args()
    report_dir = ROOT / "reports" / "packaging"
    report_dir.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    env.update(PYTHONNOUSERSITE="1", PYTHONIOENCODING="utf-8")
    report = {"started_at_utc": datetime.now(timezone.utc).isoformat(), "label": args.label,
              "root": str(ROOT), "python": sys.version, "executable": sys.executable,
              "base_prefix": sys.base_prefix, "prefix": sys.prefix,
              "pythonpath_passed_to_children": False, "commands": [],
              "packages": sorted({d.metadata["Name"] + "==" + d.version for d in distributions()}),
              "editable_installs": [d.metadata["Name"] for d in distributions()
                                    if (d.read_text("direct_url.json") and json.loads(d.read_text("direct_url.json")).get("dir_info", {}).get("editable"))]}
    modules = {}
    for name in ("intake", "engine", "selection", "scheduler", "choice_route", "cards"):
        module = importlib.import_module("prime_checkup." + name)
        modules[module.__name__] = module.__file__
    report["module_files"] = modules
    report["all_module_files_inside_package"] = all(Path(p).resolve().is_relative_to(ROOT) for p in modules.values())
    report["active_sha256"] = {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                              for folder in (ROOT / "prime_checkup", ROOT / "tests", ROOT / "tools")
                              for p in sorted(folder.rglob("*")) if p.is_file() and "__pycache__" not in p.parts}
    cases = [
        ("regression", ["-m", "unittest", "discover", "-s", "tests", "-v"]),
        ("compat", ["-m", "prime_checkup.compat"]),
        ("scenarios", ["-m", "tools.run_scenarios", "--phase", args.label, "--output", f"scenario_{args.label}_results.json"]),
        ("http", ["-m", "tools.smoke_api", "--output", f"http_{args.label}.json"]),
    ]
    for name, arguments in cases:
        command = [sys.executable, "-s", "-X", "utf8", *arguments]
        log_path = report_dir / f"{name}_{args.label}.log"
        with log_path.open("w", encoding="utf-8") as log:
            completed = subprocess.run(command, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
        output = log_path.read_text(encoding="utf-8")
        row = {"name": name, "command": command, "cwd": str(ROOT), "returncode": completed.returncode,
               "log": log_path.relative_to(ROOT).as_posix(), "verdict": "PASS" if completed.returncode == 0 else "FAIL"}
        if name == "regression":
            count = re.search(r"Ran (\d+) tests?", output)
            row["tests_run"] = int(count[1]) if count else None
        report["commands"].append(row)
        print(name, row["verdict"], flush=True)
    report["summary"] = {"commands": len(cases), "failed": sum(r["returncode"] != 0 for r in report["commands"]),
                         "all_module_files_inside_package": report["all_module_files_inside_package"],
                         "editable_installs": report["editable_installs"]}
    (report_dir / f"verification_{args.label}.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report["summary"]))
    return int(bool(report["summary"]["failed"] or not report["all_module_files_inside_package"] or report["editable_installs"]))


if __name__ == "__main__":
    raise SystemExit(main())
