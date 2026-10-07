import json
import tempfile
import tomllib
import unittest
from pathlib import Path
from unittest.mock import patch

from moodle_tasks.agents import AGENTS, detect_agents, register_agent


class AgentTests(unittest.TestCase):
    def test_detection_distinguishes_commands_configurations_and_existing_moodle(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "codex").write_text('[mcp_servers.moodle]\ncommand="python"\n', encoding="utf-8")
            (root / "claude").write_text('{"mcpServers":{"moodle":{"command":"python"}}}', encoding="utf-8")
            (root / "antigravity").write_text('invalid json', encoding="utf-8")
            with patch("moodle_tasks.agents.agent_config_file", side_effect=lambda agent: root / agent), patch("moodle_tasks.agents.shutil.which", side_effect=lambda name: "/bin/" + name if name in ("codex", "agy") else None), patch("pathlib.Path.home", return_value=root):
                result = detect_agents()
            self.assertEqual(result["codex"].availability, "Instalado")
            self.assertTrue(result["codex"].moodle_configured)
            self.assertEqual(result["claude"].availability, "Configuración encontrada")
            self.assertTrue(result["claude"].moodle_configured)
            self.assertEqual(result["antigravity"].availability, "Instalado")
            self.assertFalse(result["antigravity"].moodle_configured)
            self.assertEqual(result["copilot"].availability, "No detectado")

    def test_vscode_alone_does_not_confirm_copilot(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch("moodle_tasks.agents.agent_config_file", side_effect=lambda agent: root / agent), patch("moodle_tasks.agents.shutil.which", side_effect=lambda name: "code" if name == "code" else None), patch("pathlib.Path.home", return_value=root):
                self.assertEqual(detect_agents()["copilot"].availability, "VS Code instalado; Copilot sin confirmar")
                (root / ".vscode/extensions/github.copilot-chat-1.0").mkdir(parents=True)
                self.assertEqual(detect_agents()["copilot"].availability, "Instalado")

    def test_each_agent_keeps_existing_configuration_and_omits_credentials(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for agent in AGENTS:
                with self.subTest(agent=agent):
                    path = root / agent
                    if agent == "codex":
                        path.write_text('# comentario\nmodel = "example"\n[mcp_servers.other]\ncommand = "other"\n')
                    else:
                        key = "servers" if agent == "copilot" else "mcpServers"
                        path.write_text(json.dumps({"other_setting": True, key: {"other": {"command": "other"}}}))
                    register_agent(agent, root / "credentials.env", path)
                    first = path.read_text()
                    register_agent(agent, root / "credentials.env", path)
                    self.assertEqual(path.read_text(), first)
                    if agent == "codex":
                        data = tomllib.loads(first)
                        self.assertIn('# comentario', first)
                        self.assertEqual(data["model"], "example")
                        servers = data["mcp_servers"]
                        self.assertEqual(servers["moodle"]["tool_timeout_sec"], 300)
                    else:
                        data = json.loads(first)
                        self.assertTrue(data["other_setting"])
                        servers = data[key]
                    self.assertIn("other", servers)
                    self.assertIn("--env-file", servers["moodle"]["args"])
                    self.assertNotIn("MOODLE_PASSWORD", first)

    def test_broken_configuration_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            for agent in AGENTS:
                path = Path(directory) / agent
                path.write_text("invalid configuration")
                with self.subTest(agent=agent), self.assertRaises(Exception):
                    register_agent(agent, Path(directory) / "credentials.env", path)
                self.assertEqual(path.read_text(), "invalid configuration")
