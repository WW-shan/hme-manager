from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class DockerArtifactTests(unittest.TestCase):
    def test_dockerfile_runs_api_service_without_browser_install(self):
        dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")

        self.assertIn("python", dockerfile)
        self.assertIn("web_app.py", dockerfile)
        self.assertIn("0.0.0.0", dockerfile)
        self.assertNotIn("playwright install", dockerfile)
        self.assertNotIn("HME_DISABLE_BROWSER_LOGIN=1", dockerfile)

    def test_dockerignore_excludes_session_and_state(self):
        dockerignore = (ROOT / ".dockerignore").read_text(encoding="utf-8")

        self.assertIn("hme-config.json", dockerignore)
        self.assertIn("state/", dockerignore)
        self.assertIn("web_app.*.log", dockerignore)

    def test_compose_mounts_data_and_sets_api_key(self):
        compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")

        self.assertIn("HME_API_KEY", compose)
        self.assertIn("ICLOUD_HME_CONFIG=/data/hme-config.json", compose)
        self.assertIn("HME_STATE_DIR=/data/state", compose)
        self.assertIn("./data:/data", compose)
        self.assertIn("/data/hme-config.json", compose)
        self.assertNotIn("/data/hme-config.json:ro", compose)
        self.assertNotIn("HME_DISABLE_BROWSER_LOGIN=1", compose)

    def test_browser_agent_is_built_from_this_repository(self):
        dockerfile = (ROOT / "Dockerfile.browser").read_text(encoding="utf-8")
        requirements = (ROOT / "browser-agent-requirements.txt").read_text(encoding="utf-8")
        compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")

        self.assertIn("browser_agent.py", dockerfile)
        self.assertIn("selenium", requirements)
        self.assertIn("hme-browser-agent", compose)
        self.assertIn("Dockerfile.browser", compose)
        self.assertIn("/data/state/browser-agent.json", compose)
        self.assertIn("hme-browser-profile", compose)


if __name__ == "__main__":
    unittest.main()
