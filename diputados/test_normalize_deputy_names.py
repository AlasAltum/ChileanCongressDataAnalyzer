import tempfile
import unittest
from collections import Counter
from pathlib import Path

from normalize_deputy_names import DeputyNames, build_name_map, rewrite


class DeputyNamesTests(unittest.TestCase):
    def setUp(self):
        self.names = DeputyNames([
            "Eduardo Cornejo Lagos",
            "Eduardo Cornejo Méndez",
            "María José Van Rysselberghe Herrera",
            "Florcita Alarcón Rojas",
            "Juan Pérez Molina",
            "Juan Pérez Martínez",
        ])

    def test_abbreviated_surnames_and_accent_insensitive_match(self):
        self.assertEqual(self.names.resolve("CORNEJO L., Eduardo"), "Eduardo Cornejo Lagos")
        self.assertEqual(self.names.resolve("Van Rysselberghe H., Maria Jose"),
                         "María José Van Rysselberghe Herrera")
        self.assertEqual(self.names.resolve("Alarcon Rojas, F."), "Florcita Alarcón Rojas")

    def test_ambiguous_or_weak_match_is_unchanged(self):
        for name in ("Pérez M., Juan", "Cornejo L., E.", "Alarcón, Florcita",
                     "Alarcón Rojas, Florencia"):
            with self.subTest(name=name):
                self.assertEqual(self.names.resolve(name), name)

    def test_official_period_roster_fills_gaps_in_the_archive(self):
        with tempfile.TemporaryDirectory() as directory:
            names = build_name_map(Path(directory))
            for name in ("Acevedo S., María Candelaria", "Acevedo Sáez, María Candelaria"):
                with self.subTest(name=name):
                    self.assertEqual(names.resolve(name), "María Candelaria Acevedo Sáez")

    def test_conflicting_spellings_for_same_official_id_are_not_mapped(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "period.csv"
            path.write_text(
                "DIPID,NombreCompleto\n"
                "1,Juan Pérez Molina\n"
                "1,Juan Peres Molina\n"
                "2,María Díaz Castro\n"
                "2,María Díaz Castro\n",
                encoding="utf-8",
            )
            names = build_name_map(path.parent, {"Juan Pérez Molina"}, period_path=path)
            for name in ("Pérez Molina, Juan", "Peres Molina, Juan"):
                with self.subTest(name=name):
                    self.assertEqual(names.resolve(name), name)
            self.assertEqual(names.resolve("Díaz Castro, María"), "María Díaz Castro")

    def test_month_rewrite_preserves_other_records_and_reports_misses(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "SupportStaff.csv"
            path.write_text(
                ',Diputado,Anio,Mes,Nombre\n'
                '0,"ALARCÓN ROJAS, Florcita",2021,10,"staff member"\n'
                '1,"Pérez M., Juan",2021,10,another\n'
                '2,"Alarcón Rojas, Florcita",2021,11,third\n',
                encoding="utf-8",
            )
            self.assertEqual(rewrite(path, self.names, ("2021", "10")),
                             (1, Counter({"Pérez M., Juan": 1})))
            self.assertEqual(
                path.read_text(encoding="utf-8"),
                ',Diputado,Anio,Mes,Nombre\n'
                '0,Florcita Alarcón Rojas,2021,10,staff member\n'
                '1,"Pérez M., Juan",2021,10,another\n'
                '2,"Alarcón Rojas, Florcita",2021,11,third\n',
            )


if __name__ == "__main__":
    unittest.main()
