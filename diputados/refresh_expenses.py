"""Refresh and validate the three Cámara expense CSVs before publishing."""

import argparse
import csv
import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from zoneinfo import ZoneInfo

from refresh_camara_expenses import REPORTS

HERE = Path(__file__).resolve().parent
FIELDS = {name: list(fields) for name, _, fields in REPORTS}


def periods(start_year, end_year, month):
    return {
        f"{year:04d}-{m:02d}"
        for year in range(start_year, end_year + 1)
        for m in range(1, (month if year == end_year else 12) + 1)
    }


def load_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def validate_rows(report, rows, year, months, deputy=None):
    validated = []
    for row in rows:
        if len(row) != len(FIELDS[report]) or not isinstance(row[0], str) or not row[0].strip():
            raise ValueError(f"{report}: invalid row shape or missing deputy")
        if row[1] != year or (deputy is not None and row[0] != deputy):
            raise ValueError(f"{report}: row does not match its report selection")
        if report == "ConsultoriasExternas":
            valid_period = row[4] in {f"{year:04d}-{m:02d}" for m in months}
        else:
            valid_period = row[2] in months
        if not valid_period:
            raise ValueError(f"{report}: row does not match its report month")
        record = [str(field) for field in row]
        if report == "CostosOperacionales":
            amount = record[4]
            if not re.fullmatch(r"-?(?:[0-9]+|[0-9]{1,3}(?:\.[0-9]{3})+|[0-9]{1,3}(?:,[0-9]{3})+)", amount):
                raise ValueError(f"{report}: invalid peso amount {amount!r}")
            record[4] = amount.replace(".", ",")
        validated.append(record)
    return validated


def load_operational(stage, year):
    report = "CostosOperacionales"
    manifest = load_json(stage / "manifest.json")
    if manifest["settings"] != {"year": year, "min_month": 1, "limit": None}:
        raise ValueError("Operational checkpoint is not an unrestricted run for the selected year")
    deputies = manifest["deputies"]
    if not deputies or len(deputies) != len(set(deputies)) or any(
        not isinstance(deputy, str) or not deputy.isdigit() for deputy in deputies
    ):
        raise ValueError("Operational checkpoint has an invalid deputy roster")
    fresh = []
    for deputy in deputies:
        data = load_json(stage / "checkpoints" / f"{report}-{deputy}.json")
        months = {int(month) for month in data["months"]}
        if months - set(range(1, 13)) or not isinstance(data["deputy"], str) or not data["deputy"].strip():
            raise ValueError(f"Invalid operational checkpoint for deputy {deputy}")
        fresh.extend(validate_rows(report, data["rows"], year, months, data["deputy"]))
    return fresh


def load_bulk(stage, report, expected_periods):
    data = load_json(stage / f"{report}.json")
    missing = sorted(expected_periods - data.keys())
    if missing:
        raise ValueError(f"{report}: missing verified months: {', '.join(missing)}")
    fresh = []
    for period in sorted(expected_periods):
        year, month = map(int, period.split("-"))
        fresh.extend(validate_rows(report, data[period], year, {month}))
    return fresh


def existing_rows(path, fields):
    if not path.exists():
        return [], False
    with path.open(encoding="utf-8", newline="") as file:
        reader = csv.reader(file)
        header = next(reader)
        indexed = header == ["", *fields]
        if not indexed and header != fields:
            raise ValueError(f"{path.name}: unexpected existing CSV header")
        rows = [row[1:] if indexed else row for row in reader]
        if any(len(row) != len(fields) or not row[0].strip() for row in rows):
            raise ValueError(f"{path.name}: invalid existing CSV row")
        return rows, indexed


def replacement_key(report, row):
    if report == "CostosOperacionales":
        return tuple(row[:3])
    if report == "SupportStaff":
        return tuple(row[1:3])
    return row[4] if re.fullmatch(r"[0-9]{4}-[0-9]{2}", row[4]) else None


def latest_month(report, rows):
    def month(row):
        if report != "ConsultoriasExternas":
            return f"{int(row[1]):04d}-{int(row[2]):02d}"
        if replacement_key(report, row):
            return row[4]
        try:
            return datetime.strptime(row[4].strip(), "%d %b %Y").strftime("%Y-%m")
        except ValueError:
            return ""

    return max(map(month, rows), default="") or "undated"


def publish(stage, destination, year, month, bulk_start_year):
    expected = periods(bulk_start_year, year, month)
    fresh = {"CostosOperacionales": load_operational(stage / "operational", year)}
    for report in ("ConsultoriasExternas", "SupportStaff"):
        fresh[report] = load_bulk(stage / "bulk", report, expected)

    outputs = {}
    for report, rows in fresh.items():
        previous, indexed = existing_rows(destination / f"{report}.csv", FIELDS[report])
        replaced = {replacement_key(report, row) for row in rows}
        merged = [row for row in previous if replacement_key(report, row) not in replaced] + rows
        if not merged:
            raise ValueError(f"{report}: refusing to publish an empty dataset")
        outputs[report] = merged, indexed, latest_month(report, merged)

    destination.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=destination) as pending:
        for report, (rows, indexed, latest) in outputs.items():
            file = Path(pending) / f"{report}.csv"
            with file.open("w", encoding="utf-8", newline="") as stream:
                writer = csv.writer(stream, lineterminator="\n")
                writer.writerow(["", *FIELDS[report]] if indexed else FIELDS[report])
                writer.writerows(([index, *row] for index, row in enumerate(rows)) if indexed else rows)
        for report, (rows, _, latest) in outputs.items():
            filename = f"{report}.csv"
            (Path(pending) / filename).replace(destination / filename)
            print(f"{filename}: {len(rows):,} rows; latest populated month {latest}")


def refresh(args):
    if not args.publish_only:
        commands = [
            ["refresh_camara_expenses.py", "--out", str(args.stage / "operational"),
             "--year", str(args.year), "--report", "CostosOperacionales"],
            ["refresh_camara_bulk_expenses.py", "--out", str(args.stage / "bulk"),
             "--start-year", str(args.bulk_start_year), "--end-year", str(args.year),
             "--end-month", str(args.month)],
        ]
        for script, *options in commands:
            subprocess.run([sys.executable, str(HERE / script), *options], check=True)
    publish(args.stage, args.output_dir, args.year, args.month, args.bulk_start_year)


def main():
    today = datetime.now(ZoneInfo("America/Santiago")).date()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--year", type=int, default=today.year)
    parser.add_argument("--month", type=int, choices=range(1, 13), default=today.month)
    parser.add_argument("--bulk-start-year", type=int)
    parser.add_argument("--stage", type=Path)
    parser.add_argument("--output-dir", type=Path, default=HERE / "collected_data")
    parser.add_argument("--publish-only", action="store_true", help="validate existing checkpoints without browsing")
    args = parser.parse_args()
    args.bulk_start_year = args.bulk_start_year if args.bulk_start_year is not None else args.year
    if not 2018 <= args.bulk_start_year <= args.year:
        parser.error("require 2018 <= bulk start year <= year")
    if args.stage is None:
        selection = f"{args.bulk_start_year}-{args.year}-{args.month:02d}"
        args.stage = Path.home() / ".local" / "state" / "camara-expenses" / f"{today.isoformat()}-{selection}"
    refresh(args)


if __name__ == "__main__":
    main()
