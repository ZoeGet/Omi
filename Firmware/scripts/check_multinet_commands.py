from __future__ import annotations

import json
import re
from pathlib import Path


EXPECTED_COMMAND_IDS = {
    "wake": 1,
    "increase": 2,
    "decrease": 3,
    "red": 4,
    "green": 5,
    "blue": 6,
    "yellow": 7,
    "purple": 8,
    "cyan": 9,
    "white": 10,
    "rainbow": 11,
    "breathe": 12,
    "sweep": 13,
    "solid": 14,
    "off": 15,
    "center_expand": 16,
    "pairing": 17,
}
MAX_COMMAND_PHRASE_COUNT = 200
MAX_PHONEME_LENGTH = 63

COMMAND_CONFIG_PATTERN = re.compile(
    r"\{\s*(?P<command_id>\d+)\s*,\s*\"(?P<phrase>[a-z]+(?:\s+[a-z]+)*)\"\s*\}"
)


def parse_config_file(config_header: Path) -> list[tuple[int, str]]:
    source = config_header.read_text(encoding="utf-8")
    array_match = re.search(
        r"kVoiceCommandPhrases\s*\[\s*\]\s*=\s*\{(?P<body>.*?)\};",
        source,
        flags=re.DOTALL,
    )
    if array_match is None:
        raise ValueError(
            f"{config_header}: missing kVoiceCommandPhrases configuration array"
        )

    body = array_match.group("body")
    commands = [
        (int(match.group("command_id")), match.group("phrase"))
        for match in COMMAND_CONFIG_PATTERN.finditer(body)
    ]
    if not commands:
        raise ValueError(f"{config_header}: command configuration is empty")
    if len(commands) > MAX_COMMAND_PHRASE_COUNT:
        raise ValueError(
            f"{config_header}: too many phrases ({len(commands)}); "
            f"MultiNet supports at most {MAX_COMMAND_PHRASE_COUNT}"
        )

    unmatched_body = COMMAND_CONFIG_PATTERN.sub("", body)
    unmatched_body = re.sub(r"//.*", "", unmatched_body)
    unmatched_body = re.sub(r"/\*.*?\*/", "", unmatched_body, flags=re.DOTALL)
    unmatched_body = unmatched_body.replace(",", "").strip()
    if unmatched_body:
        raise ValueError(
            f"{config_header}: invalid command entry near '{unmatched_body[:80]}'"
        )
    return commands


def sync_command_file(commands: list[tuple[int, str]], command_file: Path) -> None:
    command_file.parent.mkdir(parents=True, exist_ok=True)
    command_file.write_text(
        "".join(f"{command_id} {phrase}\n" for command_id, phrase in commands),
        encoding="utf-8",
        newline="\n",
    )


def validate_command_entries(
    commands: list[tuple[int, str]], source: Path
) -> None:
    seen_phrases: set[str] = set()
    for command_id, phrase in commands:
        if command_id <= 0:
            raise ValueError(f"{source}: command id must be positive")
        if not re.fullmatch(r"[a-z]+(?:\s+[a-z]+)*", phrase):
            raise ValueError(f"{source}: phrase must use lowercase pinyin words")
        if len(phrase) > MAX_PHONEME_LENGTH:
            raise ValueError(
                f"{source}: phrase exceeds {MAX_PHONEME_LENGTH} characters"
            )
        if phrase in seen_phrases:
            raise ValueError(f"{source}: duplicate phrase '{phrase}'")
        seen_phrases.add(phrase)

    command_ids = {command_id for command_id, _ in commands}
    missing_ids = set(EXPECTED_COMMAND_IDS.values()) - command_ids
    if missing_ids:
        raise ValueError(f"{source}: missing command ids {sorted(missing_ids)}")
    wake_phrase_count = sum(current_id == EXPECTED_COMMAND_IDS["wake"]
                            for current_id, _ in commands)
    if wake_phrase_count != 1:
        raise ValueError(
            f"{source}: expected exactly one wake phrase for id 1, "
            f"found {wake_phrase_count}"
        )
    if len(commands) > MAX_COMMAND_PHRASE_COUNT:
        raise ValueError(
            f"{source}: too many phrases ({len(commands)}); "
            f"MultiNet supports at most {MAX_COMMAND_PHRASE_COUNT}"
        )


def parse_runtime_ids(runtime_header: Path) -> dict[str, int]:
    source = runtime_header.read_text(encoding="utf-8")
    result: dict[str, int] = {}
    symbols = {
        "wake": "kWakePhraseCommandId",
        "increase": "kIncreaseBrightnessCommandId",
        "decrease": "kDecreaseBrightnessCommandId",
        "red": "kRedColorCommandId",
        "green": "kGreenColorCommandId",
        "blue": "kBlueColorCommandId",
        "yellow": "kYellowColorCommandId",
        "purple": "kPurpleColorCommandId",
        "cyan": "kCyanColorCommandId",
        "white": "kWhiteColorCommandId",
        "rainbow": "kRainbowEffectCommandId",
        "breathe": "kBreatheEffectCommandId",
        "sweep": "kSweepEffectCommandId",
        "solid": "kSolidEffectCommandId",
        "off": "kOffEffectCommandId",
        "center_expand": "kCenterExpandEffectCommandId",
        "pairing": "kOpenPairingModeCommandId",
    }
    for name, symbol in symbols.items():
        match = re.search(
            rf"constexpr\s+int\s+{symbol}\s*=\s*(\d+)\s*;", source
        )
        if match is None:
            raise ValueError(f"{runtime_header}: missing {symbol}")
        result[name] = int(match.group(1))
    return result


def validate_runtime_ids(runtime_header: Path) -> None:
    runtime_ids = parse_runtime_ids(runtime_header)
    if runtime_ids != EXPECTED_COMMAND_IDS:
        raise ValueError(
            f"{runtime_header}: command ids {runtime_ids} do not match "
            f"expected {EXPECTED_COMMAND_IDS}"
        )
    if len(set(runtime_ids.values())) != len(runtime_ids):
        raise ValueError(f"{runtime_header}: command ids must be unique")


def write_generated_header(
    commands: list[tuple[int, str]], generated_header: Path
) -> None:
    wake_phrases = [phrase for command_id, phrase in commands if command_id == 1]
    lines = [
        "#pragma once",
        "",
        "#include <cstddef>",
        "",
        "namespace OmiPetAudio {",
        "",
        "struct GeneratedCommandPhrase {",
        "  int commandId;",
        "  const char* phonemes;",
        "};",
        "",
        "constexpr GeneratedCommandPhrase kGeneratedCommandPhrases[] = {",
    ]
    lines.extend(
        f"    {{{command_id}, {json.dumps(phrase, ensure_ascii=False)}}},"
        for command_id, phrase in commands
    )
    lines.extend(
        [
            "};",
            "",
            "constexpr size_t kGeneratedCommandPhraseCount =",
            "    sizeof(kGeneratedCommandPhrases) / sizeof(kGeneratedCommandPhrases[0]);",
            f"constexpr char kGeneratedWakePhrasePinyin[] = {json.dumps(wake_phrases[0], ensure_ascii=False)};",
            "",
            "}  //  OmiPetAudio 命名空间 / OmiPetAudio namespace",
            "",
        ]
    )
    generated_header.write_text("\n".join(lines), encoding="utf-8", newline="\n")


def check_and_generate(
    config_header: Path,
    command_file: Path,
    runtime_header: Path,
    generated_header: Path,
) -> None:
    commands = parse_config_file(config_header)
    validate_command_entries(commands, config_header)
    validate_runtime_ids(runtime_header)
    sync_command_file(commands, command_file)
    generated_header.parent.mkdir(parents=True, exist_ok=True)
    write_generated_header(commands, generated_header)
    wake_phrase = next(phrase for command_id, phrase in commands if command_id == 1)
    print(
        f"[MODEL] command consistency ok ids={sorted({command_id for command_id, _ in commands})} "
        f"phrases={len(commands)} wake='{wake_phrase}' source={config_header}"
    )


if __name__ == "__main__":
    project_dir = Path(__file__).resolve().parents[1]
    check_and_generate(
        project_dir / "include" / "voice_command_config.h",
        project_dir / ".pio" / "generated" / "multinet_commands_cn.txt",
        project_dir / "include" / "multinet_command_recognizer.h",
        project_dir / "include" / "generated_multinet_commands.h",
    )
