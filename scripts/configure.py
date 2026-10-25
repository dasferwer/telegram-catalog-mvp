#!/usr/bin/env python3
"""Создать локальные реквизиты, сохранив существующую конфигурацию."""

import argparse
import os
import secrets
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path(".env"))
    args = parser.parse_args()
    template = Path(__file__).resolve().parents[1] / ".env.example"
    values = {
        key: secrets.token_urlsafe(32)
        for key in (
            "POSTGRES_PASSWORD",
            "APP_DATABASE_PASSWORD",
            "S3_ROOT_PASSWORD",
            "S3_SECRET_KEY",
        )
    }
    content = (
        "\n".join(
            line.split("=", 1)[0] + "=" + values[line.split("=", 1)[0]]
            if "=" in line and line.split("=", 1)[0] in values
            else line
            for line in template.read_text().splitlines()
        )
        + "\n"
    )
    fd = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as file:
        file.write(content)
    print("Local credentials created; keep the file private")


if __name__ == "__main__":
    main()
