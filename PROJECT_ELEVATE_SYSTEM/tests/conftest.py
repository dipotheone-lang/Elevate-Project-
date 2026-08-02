# -*- coding: utf-8 -*-
"""Pytest bootstrap — put the module directory on sys.path so the flat
PROJECT ELEVATE modules import cleanly. تهيئة الاختبارات."""
import sys
from pathlib import Path

MODULE_DIR = Path(__file__).resolve().parent.parent
if str(MODULE_DIR) not in sys.path:
    sys.path.insert(0, str(MODULE_DIR))

RATES = str(MODULE_DIR / "target_rates.json")
