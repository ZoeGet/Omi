import argparse
from importlib.metadata import distribution
import json
import os
from pathlib import Path
import re
import sys


def collect(output):
    root = Path(__file__).resolve().parent
    pattern = re.compile(r"^(licen[sc]e|copying|notice|unlicense)(?:[.-]|$)", re.I)
    packages = []
    for path, info in json.loads((root / "package-lock.json").read_text(encoding="utf-8"))["packages"].items():
        if path and not info.get("dev"):
            packages.append(("npm: " + path + " " + info["version"], root / path))
    cargo = Path(os.environ.get("CARGO_HOME", str(Path.home() / ".cargo")))
    for package in sorted((cargo / "registry/src").glob("*/*")):
        if package.is_dir():
            packages.append(("Rust build source: " + package.name, package))
    if not any(label.startswith("Rust") for label, _ in packages):
        raise RuntimeError("Cargo source licenses not found")
    packages.append(("Python", Path(sys.base_prefix)))
    texts = []
    missing = []
    for label, package in packages:
        licenses = [file for file in package.iterdir() if file.is_file() and pattern.match(file.name)]
        if not licenses:
            supplement = root / "licenses" / ("webview2-com.txt" if package.name.startswith("webview2-com") else package.name + ".txt")
            if supplement.is_file():
                licenses = [supplement]
        if not licenses:
            missing.append(label)
        texts.append(label + "\n\n" + "\n\n".join(file.read_text(encoding="utf-8", errors="replace") for file in licenses))
    texts.append("Mbed TLS 2.28.7\n\n" + (root / "build/crypto/MBEDTLS-LICENSE.txt").read_text(encoding="utf-8"))
    for name in ("pyserial", "pyinstaller", "websocket-client"):
        package = distribution(name)
        licenses = [package.locate_file(file) for file in package.files if ".dist-info/" in str(file) and pattern.match(file.name)]
        if not licenses:
            supplement = root / "licenses" / f"{name}-{package.version}.txt"
            if supplement.is_file():
                licenses = [supplement]
        if not licenses:
            missing.append(name)
        texts.append(f"Python package: {name} {package.version}\n\n" + "\n\n".join(file.read_text(encoding="utf-8", errors="replace") for file in licenses))
    if missing:
        raise RuntimeError("Missing dependency license texts: " + ", ".join(missing))
    (output / "DEPENDENCY_LICENSES.txt").write_text(("\n\n" + "=" * 72 + "\n\n").join(texts), encoding="utf-8")
    print(json.dumps(dict(licensePackages=len(packages), missing=[])))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    collect(parser.parse_args().output)
