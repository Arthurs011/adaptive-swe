import csv
from io import StringIO

from csv_import.parser import CSVParser


def test_parse_normal_rows():
    parser = CSVParser("name,qty\napple,3\npear,2\n")
    result = parser.parse()
    assert result[0]["row_count"] == 2
    assert result[1]["name"] == "apple"


def test_header_without_rows():
    parser = CSVParser("name,qty\n")
    assert parser.header() == ["name", "qty"]


def test_parse_returns_plain_list():
    parser = CSVParser("name\nbanana\n")
    result = parser.parse()
    assert result[0]["row_count"] == 1