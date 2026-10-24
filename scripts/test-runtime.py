#!/usr/bin/env python3
"""Run destructive fault checks only against this project's local test stack."""

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = ["docker", "compose", "-f", "compose.yml", "-f", "compose.test.yml"]


def run(*args: str) -> str:
    return subprocess.check_output([*COMPOSE, *args], cwd=ROOT, text=True).strip()


def main() -> None:
    # Container IDs are selected from this Compose project, never from user input.
    containers: dict[str, tuple[str, str]] = {}
    for service in ("api", "bot", "web", "postgres", "minio"):
        ids = run("ps", "-q", service).splitlines()
        expected = 2 if service in {"api", "bot", "web"} else 1
        if len(ids) != expected:
            raise SystemExit(f"Expected {expected} running {service} containers, found {len(ids)}")
        for container_id in ids:
            hostname = subprocess.check_output(
                ["docker", "inspect", "--format", "{{.Config.Hostname}}", container_id], text=True
            ).strip()
            containers[hostname] = (container_id, service)
            if expected == 1:
                containers["service:" + service] = (container_id, service)
            inspection = json.loads(
                subprocess.check_output(["docker", "inspect", container_id], text=True)
            )[0]
            if service == "bot":
                environment = dict(x.split("=", 1) for x in inspection["Config"]["Env"])
                if environment.get("TELEGRAM_API_URL") != "http://telegram-test:8081":
                    raise SystemExit("Fault checks require the isolated Telegram test adapter")
            if service in {"api", "bot", "web"}:
                assert inspection["HostConfig"]["ReadonlyRootfs"]
                assert not inspection["Mounts"]
    process = subprocess.Popen(
        [*COMPOSE, "run", "--rm", "--no-deps", "-T", "tests", "python", "tests/runtime_probe.py"],
        cwd=ROOT,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
        bufsize=1,
    )
    stopped: set[str] = set()
    assert process.stdout and process.stdin
    try:
        for line in process.stdout:
            if not line.startswith("ACTION "):
                print(line, end="", flush=True)
                continue
            command = json.loads(line[7:])
            instance = command["instance"]
            action = command["action"]
            if instance not in containers or action not in {"stop", "start", "kill"}:
                raise RuntimeError("Invalid runtime probe action")
            container_id, service = containers[instance]
            print(f"{action}: {service} {instance}", flush=True)
            args = ["docker", action]
            if action == "stop":
                args.extend(["--time", "2"])
            subprocess.run([*args, container_id], check=True, stdout=subprocess.DEVNULL)
            if action in {"stop", "kill"}:
                stopped.add(container_id)
            else:
                stopped.discard(container_id)
            process.stdin.write("ok\n")
            process.stdin.flush()
        if process.wait() != 0:
            raise SystemExit("Runtime verification failed")
    finally:
        for container_id in stopped:
            subprocess.run(
                ["docker", "start", container_id], check=False, stdout=subprocess.DEVNULL
            )
        if process.poll() is None:
            process.terminate()


if __name__ == "__main__":
    main()
