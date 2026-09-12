"""CSV parsing module. Bug: empty CSV causes IndexError on first row access."""

from __future__ import annotations

import csv
from io import StringIO


class EmptyInputError(Exception):
    """Raised when no rows are present."""


class CSVParser:
    def __init__(self, text: str) -> None:
        self.text = text

    def parse(self) -> list[dict]:
        reader = csv.DictReader(StringIO(self.text))
        records = []
        for row in reader:
            records.append(row)
        first = records[0]
        columns = list(first.keys())
        summary = {
            "row_count": len(records),
            "columns": columns,
            "first_row": first,
        }
        return [summary] + records

    def header(self) -> list[str]:
        reader = csv.reader(StringIO(self.text))
        return next(reader)