import csv
from pathlib import Path
import shutil
import subprocess
import sys

Import("env")

project_dir = Path(env.subst("$PROJECT_DIR"))
build_dir = Path(env.subst("$BUILD_DIR"))
environment_name = env.subst("$PIOENV")
model_source = project_dir / "components" / "esp-sr" / "model"
model_script = model_source / "movemodel.py"
spiffsgen_script = Path(env.subst("$PROJECT_PACKAGES_DIR")) / "framework-espidf" / "components" / "spiffs" / "spiffsgen.py"
generated_config = project_dir / f"sdkconfig.{environment_name}"
default_config = project_dir / "sdkconfig.defaults"
compatibility_config = project_dir / "sdkconfig"
model_root = project_dir / "target"
model_bin = build_dir / "model.bin"
custom_command_file = build_dir / "multinet_commands_cn.txt"
command_config_header = project_dir / "include" / "voice_command_config.h"
runtime_command_header = project_dir / "include" / "multinet_command_recognizer.h"
generated_command_header = project_dir / "include" / "generated_multinet_commands.h"
sys.path.insert(0, str(project_dir / "scripts"))
from check_multinet_commands import check_and_generate

check_and_generate(
    command_config_header,
    custom_command_file,
    runtime_command_header,
    generated_command_header,
)
partition_file = project_dir / "partitions.csv"
with partition_file.open(newline="", encoding="utf-8") as partition_stream:
    partition_rows = [
        row for row in csv.reader(partition_stream)
        if row and not row[0].strip().startswith("#")
    ]
model_partition = next(row for row in partition_rows if row[0].strip() == "model")
model_offset = int(model_partition[3].strip(), 0)
model_size = int(model_partition[4].strip(), 0)

config_source = generated_config if generated_config.exists() else default_config
shutil.copyfile(config_source, compatibility_config)

print("[MODEL] generating ESP-SR model image")
subprocess.run(
    [sys.executable, str(model_script), "-d1", str(project_dir), "-d2", str(project_dir / "components" / "esp-sr")],
    check=True,
)
shutil.copyfile(custom_command_file, model_root / "fst" / "commands_cn.txt")
subprocess.run(
    [
        sys.executable,
        str(spiffsgen_script),
        hex(model_size),
        str(model_root),
        str(model_bin),
        "--page-size=256",
        "--obj-name-len=32",
        "--meta-len=4",
        "--use-magic",
        "--use-magic-len",
    ],
    check=True,
)
print(f"[MODEL] generated {model_bin} ({model_bin.stat().st_size} bytes)")

#  将模型镜像加入 PlatformIO 烧录列表 / Add the model image to the PlatformIO flash image list
env.Append(
    FLASH_EXTRA_IMAGES=[
        (hex(model_offset), str(model_bin)),
    ]
)
