import json
import tempfile
import tomllib
import unittest
from pathlib import Path

from moodle_tasks.agents import AGENTS, register_agent


class AgentTests(unittest.TestCase):
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
