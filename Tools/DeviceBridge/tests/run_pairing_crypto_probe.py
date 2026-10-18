import argparse
import json
import os
from pathlib import Path
import subprocess
import tempfile


def main():
    parser = argparse.ArgumentParser(description="Offline EC J-PAKE primitive probe; no network or firmware changes")
    parser.add_argument("--mbedtls-dir", type=Path, required=True)
    parser.add_argument("--wsl-distro")
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    if os.name == "nt" and not args.wsl_distro:
        parser.error("Windows requires an explicit existing WSL distribution")
    source = args.mbedtls_dir.resolve()
    if not (source / "library/ecjpake.c").is_file():
        parser.error("Installed Mbed TLS source with EC J-PAKE required")
    repository = Path(__file__).resolve().parents[3]
    native = Path(__file__).resolve().parent / "native/pairing_ecjpake_probe.cpp"
    scratch = repository / "tmp"
    scratch.mkdir(exist_ok=True)

    def native_path(value):
        value = str(Path(value).resolve())
        if os.name == "nt":
            return "/mnt/" + value[0].lower() + value[2:].replace("\\", "/")
        return value

    def run(command, timeout=300):
        prefix = (["wsl", "-d", args.wsl_distro, "--exec", "env", "LC_ALL=C"]
                  if os.name == "nt" else [])
        result = subprocess.run(prefix + command, capture_output=True, text=True,
                                encoding="utf-8", timeout=timeout)
        if result.returncode:
            raise RuntimeError(result.stdout + result.stderr)
        return result.stdout

    with tempfile.TemporaryDirectory(prefix="pairing-crypto-probe-", dir=scratch) as directory:
        temporary = Path(directory)
        config = temporary / "pairing_user_config.h"
        config.write_text("#define MBEDTLS_ECJPAKE_C\n", encoding="ascii")
        build = temporary / "build"
        flags = "-include " + native_path(config)
        run(["cmake", "-S", native_path(source), "-B", native_path(build),
             "-DENABLE_PROGRAMS=OFF", "-DENABLE_TESTING=OFF",
             "-DMBEDTLS_FATAL_WARNINGS=OFF", "-DCMAKE_C_FLAGS=" + flags])
        run(["cmake", "--build", native_path(build), "--target", "mbedcrypto", "--parallel", "4"])
        run(["cmake", "--build", native_path(build), "--target", "mbedx509", "--parallel", "4"])
        executable = temporary / "pairing_ecjpake_probe"
        run(["g++", "-std=c++11", "-Wall", "-Wextra", "-Werror", "-include", native_path(config),
             "-I" + native_path(source / "include"),
             "-I" + native_path(repository / "Firmware/include"), native_path(native),
             native_path(build / "library/libmbedcrypto.a"), "-pthread", "-o", native_path(executable)])
        output = run([native_path(executable)], timeout=120)
        nvs_executable = temporary / "pairing_nvs_native"
        mock_include = Path(__file__).resolve().parent / "native/mock_idf"
        nvs_native = Path(__file__).resolve().parent / "native/pairing_nvs_native.cpp"
        nvs_adapter = repository / "Firmware/src/pairing_nvs_store.cpp"
        run(["g++", "-std=c++11", "-Wall", "-Wextra", "-Werror",
             "-I" + native_path(mock_include),
             "-I" + native_path(source / "include"),
             "-I" + native_path(repository / "Firmware/include"),
             native_path(nvs_native), native_path(nvs_adapter),
             native_path(build / "library/libmbedcrypto.a"), "-pthread",
             "-o", native_path(nvs_executable)])
        output += run([native_path(nvs_executable)], timeout=120)
        tls_executable = temporary / "pairing_tls_native"
        tls_native = Path(__file__).resolve().parent / "native/pairing_tls_native.cpp"
        tls_source = repository / "Firmware/src/pairing_tls_identity.cpp"
        run(["g++", "-std=c++11", "-Wall", "-Wextra", "-Werror",
             "-I" + native_path(source / "include"),
             "-I" + native_path(repository / "Firmware/include"),
             native_path(tls_native), native_path(tls_source),
             native_path(build / "library/libmbedx509.a"),
             native_path(build / "library/libmbedcrypto.a"), "-pthread",
             "-o", native_path(tls_executable)])
        output += run([native_path(tls_executable)], timeout=120)
        tls_store_executable = temporary / "pairing_tls_store_native"
        tls_store_native = Path(__file__).resolve().parent / "native/pairing_tls_store_native.cpp"
        tls_store_source = repository / "Firmware/src/pairing_tls_store.cpp"
        run(["g++", "-std=c++11", "-Wall", "-Wextra", "-Werror",
             "-I" + native_path(mock_include),
             "-I" + native_path(source / "include"),
             "-I" + native_path(repository / "Firmware/include"),
             native_path(tls_store_native), native_path(tls_source),
             native_path(tls_store_source),
             native_path(build / "library/libmbedx509.a"),
             native_path(build / "library/libmbedcrypto.a"), "-pthread",
             "-o", native_path(tls_store_executable)])
        output += run([native_path(tls_store_executable)], timeout=120)
    checks = [line[5:] for line in output.splitlines() if line.startswith("PASS ")]
    if len(checks) != 23:
        raise RuntimeError("Unexpected primitive probe result")
    report = dict(result="pass", primitive="Mbed TLS 2.28.7 low-level EC J-PAKE",
                  checks=checks, noTlsEcjpakeCipherSuite=True, networkEnabled=False,
                  activeFirmwareChanged=False, isolatedFirmwareCodeAdded=True,
                  firmwareFlashed=False,
                  pending="TLS runtime integration, credential issuance, full firmware build and device validation")
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(output, end="")


if __name__ == "__main__":
    main()
