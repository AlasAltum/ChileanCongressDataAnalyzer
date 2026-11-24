"""Normalize bulk-report deputy names using the operational roster and archive."""

import argparse
import csv
import io
import re
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path
from tempfile import NamedTemporaryFile

REPORT_COLUMNS = {
    "CostosOperacionales": "diputado",
    "ConsultoriasExternas": "Diputado",
    "SupportStaff": "Diputado",
}
BULK_REPORTS = ("ConsultoriasExternas", "SupportStaff")


def tokens(value):
    folded = "".join(char for char in unicodedata.normalize("NFKD", value.casefold())
                     if not unicodedata.combining(char))
    return tuple(re.findall(r"[^\W\d_]+\.?", folded))


def initial(token):
    return len(token) == 2 and token.endswith(".")


def given_matches(report, known):
    return all(left[0] == right[0] if initial(left) else left == right
               for left, right in zip(report, known))


class DeputyNames:
    def __init__(self, names):
        self.by_surnames = defaultdict(set)
        self.resolved = {}
        for name in set(names):
            if "," in name:
                continue
            parts = tokens(name)
            for split in range(1, len(parts) - 1):
                given, surnames = parts[:split], parts[split:]
                self.by_surnames[surnames].add((given, name))
                self.by_surnames[surnames[:-1] + (surnames[-1][0] + ".",)].add((given, name))

    def resolve(self, name):
        if name not in self.resolved:
            self.resolved[name] = self._resolve(name)
        return self.resolved[name]

    def _resolve(self, name):
        if name.count(",") != 1:
            return name
        surname_text, given_text = name.split(",")
        surnames, given = tokens(surname_text), tokens(given_text)
        if len(surnames) < 2 or not given or (initial(surnames[-1]) and initial(given[0])):
            return name
        candidates = {full for known_given, full in self.by_surnames.get(surnames, ())
                      if given_matches(given, known_given)}
        return candidates.pop() if len(candidates) == 1 else name


def read_archive_names(directory):
    names = set()
    for report, column in REPORT_COLUMNS.items():
        path = directory / f"{report}.csv"
        if path.exists():
            with path.open(encoding="utf-8", newline="") as stream:
                names.update(row[column] for row in csv.DictReader(stream) if row[column])
    return names


def normalize_rows(rows, column, names):
    changed = 0
    unresolved = Counter()
    for row in rows:
        original = row[column]
        if "," not in original:
            continue
        row[column] = names.resolve(original)
        if row[column] == original:
            unresolved[original] += 1
        else:
            changed += 1
    return changed, unresolved


def show_result(report, changed, unresolved):
    print(f"{report}: {changed:,} deputy names normalized; "
          f"{sum(unresolved.values()):,} rows with {len(unresolved)} unmatched or ambiguous names.")
    for name, count in sorted(unresolved.items()):
        print(f"  {count:>6}  {name}")


def rewrite(path, names, period=None):
    with path.open(encoding="utf-8", newline="") as stream:
        original = stream.readlines()
    reader = csv.reader(original)
    header = next(reader)
    column = header.index(REPORT_COLUMNS[path.stem])
    year = header.index("Anio")
    month = header.index("Mes") if period else None
    output = original[:reader.line_num]
    start = reader.line_num
    changed = 0
    unresolved = Counter()
    for row in reader:
        raw = original[start:reader.line_num]
        start = reader.line_num
        prior = row[column]
        if period is None or (row[year], row[month].zfill(2)) == period:
            count, misses = normalize_rows([row], column, names)
            changed += count
            unresolved.update(misses)
        if row[column] != prior:
            line = io.StringIO(newline="")
            csv.writer(line, lineterminator="\n").writerow(row)
            output.append(line.getvalue())
        else:
            output.extend(raw)
    if changed:
        with NamedTemporaryFile(mode="w", encoding="utf-8", newline="", dir=path.parent,
                                delete=False) as stream:
            temporary = Path(stream.name)
            stream.writelines(output)
        temporary.chmod(path.stat().st_mode)
        temporary.replace(path)
    return changed, unresolved


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=Path(__file__).with_name("collected_data"))
    parser.add_argument("--staff-month", help="only rewrite support staff for YYYY-MM")
    args = parser.parse_args()
    if args.staff_month and not re.fullmatch(r"[0-9]{4}-(0[1-9]|1[0-2])", args.staff_month):
        parser.error("--staff-month must be YYYY-MM")
    names = DeputyNames(read_archive_names(args.data_dir))
    for report in ("SupportStaff",) if args.staff_month else BULK_REPORTS:
        period = tuple(args.staff_month.split("-")) if args.staff_month else None
        show_result(report, *rewrite(args.data_dir / f"{report}.csv", names, period))


if __name__ == "__main__":
    main()
