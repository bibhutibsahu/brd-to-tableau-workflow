"""Shared agent plumbing: identity, LLM access and the artifact folders each step writes to."""

import json
from pathlib import Path

import config
from modules.llm_client import LLMClient, LLMError

STEP_FOLDERS = {1: "step1_brd", 2: "step2_mockup", 3: "step3_{platform}"}


def slug(text: str) -> str:
    from modules.dashboard_generator import slug as _slug

    return _slug(text or "project")


def project_dir(project_name: str, root: Path | None = None) -> Path:
    return Path(root or config.OUTPUT_DIR) / slug(project_name)


def step_dir(project_name: str, step: int, platform: str = "", root: Path | None = None) -> Path:
    folder = project_dir(project_name, root) / STEP_FOLDERS[step].format(platform=platform or "platform")
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def write_json(path: Path, value) -> Path:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, default=str), encoding="utf-8", newline="\n")
    return path


def write_text(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8", newline="\n")
    return path


def read_json(path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


class Agent:
    """One step of the workflow. Subclasses set the class attributes and implement their own methods."""

    step: int = 0
    name: str = "Agent"
    role: str = ""
    inputs: str = ""
    outputs: str = ""
    uses_llm: bool = True

    def __init__(self, llm: LLMClient | None = None):
        self.llm = llm

    def require_llm(self) -> LLMClient:
        if self.llm is None or not self.llm.available:
            raise LLMError(
                f"{self.name} needs a Gemini API key. Enter it in the sidebar or set GEMINI_API_KEY in .env."
            )
        return self.llm

    @classmethod
    def card(cls) -> dict:
        """Short description for the UI and docs."""
        return {
            "step": cls.step,
            "name": cls.name,
            "role": cls.role,
            "inputs": cls.inputs,
            "outputs": cls.outputs,
            "uses_llm": cls.uses_llm,
        }
