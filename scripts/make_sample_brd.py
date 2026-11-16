"""Write data/sample_brd.pdf and data/sample_brd.docx: an ecommerce analytics BRD for testing.

Run:  python scripts/make_sample_brd.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import DATA_DIR  # noqa: E402

TITLE = "ShopSphere Ecommerce Performance Dashboards - Business Requirements Document"
SECTIONS = [
    ("1. Document Control", [
        "Version 1.2 | Owner: Head of Analytics | Business sponsor: Chief Commercial Officer",
        "Status: Approved for build | Target tool: Tableau",
    ]),
    ("2. Business Objective", [
        "ShopSphere sells electronics, fashion, home, beauty, sports and books across India through its website, "
        "mobile app and marketplace partners. Leadership needs one trusted set of dashboards to track revenue growth, "
        "profitability, customer retention, promotion effectiveness and delivery performance on a monthly basis, "
        "replacing manual Excel reports.",
    ]),
    ("3. Stakeholders", [
        "CXO leadership team, Category Managers, Growth & Marketing team, Supply Chain & Operations team.",
    ]),
    ("4. Data Source", [
        "Sales data warehouse (star schema): fact_sales at order-line grain with dimensions for date, customer, "
        "product, geography, channel and promotion. Data refreshes daily; reporting grain is monthly.",
    ]),
    ("5. Global Filters", [
        "All dashboards must allow filtering by Month, Region, Product Category and Sales Channel.",
    ]),
    ("6. Dashboard 1 - Executive Sales Overview (Audience: CXO)", [
        "KPIs: Net Revenue, Total Orders, Average Order Value (AOV), Gross Margin %, Active Customers.",
        "FR-1.1 Show the monthly Net Revenue trend for the last 12 months as a line chart.",
        "FR-1.2 Show Net Revenue by Product Category to identify the biggest categories.",
        "FR-1.3 Show Net Revenue by Region.",
        "FR-1.4 Show the share of Orders by Sales Channel (website, app, marketplace).",
    ]),
    ("7. Dashboard 2 - Customer Insights (Audience: Growth team)", [
        "KPIs: Active Customers, New Customers, Repeat Order Rate, Revenue per Customer.",
        "FR-2.1 Revenue by Customer Segment (VIP, Loyal, Regular, Occasional).",
        "FR-2.2 Monthly trend of New Customers acquired.",
        "FR-2.3 Customers by Age Group.",
        "FR-2.4 AOV by Acquisition Source to compare quality of acquisition channels.",
    ]),
    ("8. Dashboard 3 - Product & Category Performance (Audience: Category Managers)", [
        "KPIs: Units Sold, Gross Profit, Gross Margin %, Return Rate.",
        "FR-3.1 Top 10 Products by Net Revenue.",
        "FR-3.2 Gross Margin % by Category.",
        "FR-3.3 Return Rate by Sub-Category to flag quality issues.",
        "FR-3.4 Units Sold by Brand, top 10 brands.",
    ]),
    ("9. Dashboard 4 - Marketing & Promotions (Audience: Marketing)", [
        "KPIs: Discount Given, Discount Rate, Net Revenue, New Customers.",
        "FR-4.1 Net Revenue by Traffic Source.",
        "FR-4.2 Discount Rate by Promotion Type.",
        "FR-4.3 Net Revenue by Promotion campaign.",
    ]),
    ("10. Dashboard 5 - Fulfilment & Returns (Audience: Operations)", [
        "KPIs: Average Delivery Days, Shipping Cost, Return Rate, Cancellation Rate.",
        "FR-5.1 Average Delivery Days by City Tier.",
        "FR-5.2 Cancellation Rate by Payment Method (COD is a known risk).",
        "FR-5.3 Monthly Return Rate trend.",
    ]),
    ("11. KPI Definitions", [
        "Net Revenue = gross sales minus discounts, excluding cancelled orders.",
        "AOV = Net Revenue / number of distinct orders.",
        "Gross Margin % = (Net Revenue - COGS) / Net Revenue.",
        "Repeat Order Rate = orders from returning customers / total orders.",
        "Return Rate = value of returned items / Net Revenue.",
        "Discount Rate = discount amount / gross sales.",
    ]),
    ("12. Non-Functional Requirements", [
        "Dashboards must load in under 5 seconds, use consistent INR currency formatting, and follow corporate colours.",
    ]),
    ("13. Open Points", [
        "Customer lifetime value (CLV) definition is pending approval from Finance.",
        "Net Promoter Score (NPS) data is not yet available in the warehouse.",
    ]),
]


def write_docx(path: Path):
    from docx import Document

    doc = Document()
    doc.add_heading(TITLE, level=0)
    for heading, paragraphs in SECTIONS:
        doc.add_heading(heading, level=1)
        for text in paragraphs:
            doc.add_paragraph(text, style="List Bullet" if text.startswith(("FR-", "KPIs")) else None)
    doc.save(path)


def write_pdf(path: Path):
    from fpdf import FPDF

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 15)
    pdf.multi_cell(0, 8, TITLE, new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)
    for heading, paragraphs in SECTIONS:
        pdf.set_font("Helvetica", "B", 12)
        pdf.multi_cell(0, 7, heading, new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 10)
        for text in paragraphs:
            pdf.multi_cell(0, 5.5, ("- " if text.startswith(("FR-", "KPIs")) else "") + text, new_x="LMARGIN", new_y="NEXT")
        pdf.ln(2)
    pdf.output(str(path))


if __name__ == "__main__":
    DATA_DIR.mkdir(exist_ok=True)
    write_pdf(DATA_DIR / "sample_brd.pdf")
    write_docx(DATA_DIR / "sample_brd.docx")
    print(f"Wrote {DATA_DIR / 'sample_brd.pdf'} and {DATA_DIR / 'sample_brd.docx'}")
