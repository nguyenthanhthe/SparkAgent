"""CSV demo: describe / filter / sort / group over an inline table.

Exercises the same :class:`tools.csv_tool.Table` surface the
``csv_analyze`` tool exposes — parse, column types with missing-cell
counts, comparison filters, sort, and group aggregates — fully offline.
Also demonstrates the guardrail behavior: a numeric filter over a
column with missing cells raises ``CsvError``, so the workflow is to
narrow to a complete subset first.

    python examples/csv_demo.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.csv_tool import CsvError, Table   # noqa: E402

CSV_TEXT = """region,host,score
emea,web-01,90
emea,web-02,75
apac,web-03,88
apac,web-04,
emea,web-05,60
"""


def main() -> None:
    table = Table.parse(CSV_TEXT)

    print("describe:")
    info = table.describe()
    print(f"  rows={info['rows']} columns={info['columns']}")
    for column, kind in info["column_types"].items():
        print(f"  {column}: {kind} (missing={info['missing'][column]})")

    try:
        table.filter("score", ">", "70")
    except CsvError as exc:
        print(f"\nnumeric filter over missing cells: {exc}")

    emea = table.filter("region", "==", "emea")
    print("\nemea subset sorted by score:")
    for row in emea.sort("score", descending=True).head(5):
        print(f"  {row['host']:7s} {row['score']}")

    print("\ngroup score by region (missing cells skipped):")
    for region, agg in sorted(table.group_aggregate("region", "score")
                              .items()):
        print(f"  {region}: n={agg['count']} avg={agg['avg']:g} "
              f"sum={agg['sum']:g}")


if __name__ == "__main__":
    main()
