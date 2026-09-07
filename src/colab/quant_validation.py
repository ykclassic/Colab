"""Deterministic quantitative validation primitives with reproducible results."""

from __future__ import annotations

import hashlib
import json
import math

from collections.abc import Callable, Sequence
from dataclasses import dataclass
