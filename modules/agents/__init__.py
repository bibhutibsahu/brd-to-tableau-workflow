"""The three agents of the BRD -> dashboard workflow. Each one reads the previous step's artifact
from disk and writes its own, so a step can be re-run, reviewed or handed over on its own.

Step 1  BRDAnalystAgent         customer BRD  -> brd_final.json (+ .md, .docx, gap_report.md)
Step 2  DashboardDesignerAgent  brd_final.json -> dashboard_spec.json (+ .md) and dashboard_mockup.html
Step 3  BIPublisherAgent        dashboard_spec.json -> Tableau workbook / Power BI hand-off pack

Artifacts live in outputs/<project>/step1_brd, step2_mockup and step3_<platform>.
"""

from modules.agents.base import Agent, project_dir, step_dir
from modules.agents.bi_publisher import PLATFORMS, BIPublisherAgent
from modules.agents.brd_analyst import BRDAnalystAgent
from modules.agents.dashboard_designer import DashboardDesignerAgent

__all__ = [
    "PLATFORMS",
    "Agent",
    "BIPublisherAgent",
    "BRDAnalystAgent",
    "DashboardDesignerAgent",
    "project_dir",
    "step_dir",
]
