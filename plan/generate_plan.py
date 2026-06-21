#!/usr/bin/env python3
"""Render plan/plan.html to plan/swim_plan_8week.pdf using WeasyPrint.

    pip install -r requirements.txt
    python3 plan/generate_plan.py
"""
import os
from weasyprint import HTML

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "plan.html")
OUT = os.path.join(HERE, "swim_plan_8week.pdf")

if __name__ == "__main__":
    HTML(SRC).write_pdf(OUT)
    print("wrote", OUT)
