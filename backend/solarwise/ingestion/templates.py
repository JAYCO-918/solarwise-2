"""Files an operator can download to see what an upload looks like.

The *templates* hold column names and no data.  The *examples* hold a few rows
of invented values for a hypothetical 1 MWp plant, so that the mapping, the
units and the event columns can be seen at work; they describe no real
installation.
"""

from __future__ import annotations

from dataclasses import dataclass
from importlib import resources


@dataclass(frozen=True)
class Template:
    name: str
    title: str
    description: str
    media_type: str
    #: The file holds invented example values (as opposed to column names only).
    example: bool


TEMPLATES: tuple[Template, ...] = (
    Template(
        "solarwise-operational-data.template.csv", "CSV template",
        "Column names with their units, and no data: fill in one row per day or per interval.",
        "text/csv; charset=utf-8", False,
    ),
    Template(
        "solarwise-operational-data.example.csv", "CSV example",
        "The same columns with 14 days of invented values for a hypothetical 1 MWp plant, one cleaning and two "
        "alarms. The values describe no real installation.",
        "text/csv; charset=utf-8", True,
    ),
    Template(
        "solarwise-operational-data.template.json", "JSON template",
        "One record with every field and no value: copy it once per day or per interval.",
        "application/json", False,
    ),
    Template(
        "solarwise-operational-data.example.json", "JSON example",
        "The 14 invented days of the CSV example, as JSON records.",
        "application/json", True,
    ),
)


def find(name: str) -> Template | None:
    return next((t for t in TEMPLATES if t.name == name), None)


def read(template: Template) -> bytes:
    return resources.files("solarwise.reference").joinpath("templates", template.name).read_bytes()
