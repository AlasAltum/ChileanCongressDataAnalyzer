import tempfile
import unittest
from collections import Counter
from pathlib import Path

from normalize_deputy_names import DeputyNames, rewrite


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
