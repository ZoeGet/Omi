import argparse
import os
from pathlib import Path
import shutil
import subprocess


def build(source, output):
    vswhere = Path(os.environ["ProgramFiles(x86)"]) / "Microsoft Visual Studio/Installer/vswhere.exe"
    install = subprocess.check_output([str(vswhere), "-latest", "-products", "*",
                                      "-property", "installationPath"], text=True).strip()
    vcvars = Path(install) / "VC/Auxiliary/Build/vcvars64.bat"
    if not vcvars.is_file():
        raise RuntimeError("Microsoft C++ Build Tools is required")
    result = subprocess.check_output(f'call "{vcvars}" >nul && set', shell=True, text=True)
    env = {name.upper(): value for name, value in os.environ.items()}
    for line in result.splitlines():
        if "=" in line and not line.startswith("="):
            name, value = line.split("=", 1)
            env[name.upper()] = value
    root = Path(__file__).resolve().parent
    cmake = shutil.which("cmake")
    if not cmake or not shutil.which("ninja"):
        raise RuntimeError("CMake and Ninja must be on PATH")
    subprocess.run([cmake, "-S", str(root), "-B", str(output / "build"), "-G", "Ninja",
                    "-DCMAKE_BUILD_TYPE=Release", f"-DMBEDTLS_SOURCE={source.as_posix()}"], env=env, check=True)
    subprocess.run([cmake, "--build", str(output / "build"), "--target", "omi_pake"], env=env, check=True)
    shutil.copy2(output / "build/omi_pake.dll", output / "omi_pake.dll")
    shutil.copy2(source / "LICENSE", output / "MBEDTLS-LICENSE.txt")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=Path.home() / ".platformio/packages/framework-espidf/components/mbedtls/mbedtls")
    parser.add_argument("--output", type=Path, default=Path(__file__).resolve().parents[2] / "Desktop/build/crypto")
    args = parser.parse_args()
    build(args.source.resolve(), args.output.resolve())
