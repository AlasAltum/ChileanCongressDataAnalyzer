import csv
import json
import tempfile
import unittest
from pathlib import Path

from refresh_expenses import FIELDS, publish


class PublishTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        self.stage = root / "stage"
        self.output = root / "collected_data"
        self.output.mkdir()
        (self.stage / "operational" / "checkpoints").mkdir(parents=True)
        (self.stage / "bulk").mkdir()
        self.write_stage("operational/manifest.json", {
            "settings": {"year": 2026, "min_month": 1, "limit": None},
            "deputies": ["123"],
        })
        self.write_stage("operational/checkpoints/CostosOperacionales-123.json", {
            "deputy": "Deputy", "months": ["1"], "rows": [["Deputy", 2026, 1, "Travel", "2.000"]],
        })
        self.write_stage("bulk/ConsultoriasExternas.json", {
            "2026-01": [["D., Deputy", 2026, "Ver", "1", "2026-01", "Advisor", "", "4"]],
        })
        self.write_stage("bulk/SupportStaff.json", {"2026-01": []})
        self.write_existing("CostosOperacionales", [
            ["Deputy", 2021, 8, "Travel", 1],
            ["Deputy", 2026, 1, "Travel", 1],
        ], indexed=True)
        self.write_existing("ConsultoriasExternas", [
            ["Deputy", 2021, "", "", "17 jun 2021", "Advisor", "Report", 3],
        ])
        self.write_existing("SupportStaff", [
            ["D., Deputy", 2026, 1, "Contract", "Worker", "Role", 5, "", ""],
        ])

    def write_stage(self, name, data):
        (self.stage / name).write_text(json.dumps(data), encoding="utf-8")

    def write_existing(self, report, rows, indexed=False):
        with (self.output / f"{report}.csv").open("w", encoding="utf-8", newline="") as file:
            writer = csv.writer(file)
            writer.writerow(["", *FIELDS[report]] if indexed else FIELDS[report])
            writer.writerows(([index, *row] for index, row in enumerate(rows)) if indexed else rows)

    def read_output(self, report):
        with (self.output / f"{report}.csv").open(encoding="utf-8", newline="") as file:
            return list(csv.reader(file))

    def test_merge_replaces_only_observed_keys_and_is_idempotent(self):
        publish(self.stage, self.output, 2026, 1, 2026)
        expected = {report: self.read_output(report) for report in FIELDS}
        self.assertEqual(expected["CostosOperacionales"][1:], [
            ["0", "Deputy", "2021", "8", "Travel", "1"],
            ["1", "Deputy", "2026", "1", "Travel", "2,000"],
        ])
        self.assertEqual([row[4] for row in expected["ConsultoriasExternas"][1:]],
                         ["17 jun 2021", "2026-01"])
        self.assertEqual(expected["SupportStaff"][1][4], "Worker")
        publish(self.stage, self.output, 2026, 1, 2026)
        self.assertEqual({report: self.read_output(report) for report in FIELDS}, expected)

    def test_missing_bulk_month_leaves_all_csvs_unchanged(self):
        original = {file.name: file.read_bytes() for file in self.output.iterdir()}
        self.write_stage("bulk/SupportStaff.json", {})
        with self.assertRaisesRegex(ValueError, "missing verified months: 2026-01"):
            publish(self.stage, self.output, 2026, 1, 2026)
        self.assertEqual({file.name: file.read_bytes() for file in self.output.iterdir()}, original)


if __name__ == "__main__":
    unittest.main()
