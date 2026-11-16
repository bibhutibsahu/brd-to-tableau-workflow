"""BRD -> Tableau pipeline modules.

brd_parser            BRD PDF / DOCX / TXT -> text
requirement_extractor text -> structured requirements JSON (LLM)
schema_mapper         star schema introspection + requirement -> metric/dimension mapping
sql_generator         SQL and KPI logic for every visual, executed on the database
visualization_planner chart type and layout plan (LLM + rules), plan revisions
dashboard_generator   preview data and the final Tableau workbook
twb_builder           Tableau XML (.twb) writer used by dashboard_generator
llm_client            thin Gemini wrapper that returns JSON
pipeline              runs the steps in order (used by app.py and the CLI)
"""
