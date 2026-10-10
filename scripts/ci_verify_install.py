"""Instalar el wheel y probar la herramienta instalada."""

import os
import subprocess
from pathlib import Path


def main() -> None:
    wheels = list(Path("dist").glob("*.whl"))
    if len(wheels) != 1:
        raise RuntimeError("Se esperaba exactamente un wheel recién construido en dist/.")
    wheel = wheels[0]
    subprocess.run(["uv", "tool", "install", "--force", "--python", "3.11", str(wheel.resolve())], check=True)
    tool_root = Path(subprocess.check_output(["uv", "tool", "dir"], text=True).strip())
    bin_root = Path(subprocess.check_output(["uv", "tool", "dir", "--bin"], text=True).strip())
    environment = tool_root / "moodle-homework-assignment"
    python = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    command = bin_root / ("mcp-moodle.exe" if os.name == "nt" else "mcp-moodle")
    subprocess.run([
        str(python), "-c",
        "import moodle_tasks; from pathlib import Path; "
        f"assert Path(moodle_tasks.__file__).resolve().is_relative_to(Path({str(environment)!r}).resolve())",
    ], check=True)
    for arguments in (["--help"], ["setup", "--help"], ["serve", "--help"]):
        subprocess.run([str(command), *arguments], check=True)
    subprocess.run([str(python), "-m", "unittest", "discover", "-s", "tests", "-v"], check=True)


if __name__ == "__main__":
    main()
