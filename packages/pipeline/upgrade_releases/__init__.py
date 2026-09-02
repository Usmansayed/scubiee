"""Registered package releases — import to load all version definitions."""

from __future__ import annotations

from pipeline.upgrade_registry import list_releases

from pipeline.upgrade_releases import v0_2_18, v0_3_7, v0_3_10, v0_3_11, v0_3_13, v0_3_14  # noqa: F401


def all_releases():
    return list_releases()
