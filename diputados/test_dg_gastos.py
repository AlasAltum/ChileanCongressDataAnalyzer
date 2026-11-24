"""
Runs the scraper's table readers against local copies of the camara.cl
tables in a headless Firefox. Needs the scraper's own dependencies
(selenium, pandas) and Firefox. Run from diputados/, where dg_gastos.py
runs and imports driver_utils:
    python -m unittest test_dg_gastos
"""
import pathlib
import tempfile
import unittest
from unittest import mock

from selenium import webdriver

import dg_gastos
from dg_gastos import DeputyWebDriver

PAGE = '''<html><body>
<a id="ContentPlaceHolder1_ContentPlaceHolder1_btnAsexterna" href="#"
   onclick="document.title='asesorias'">Asesorías externas</a>
{content}
</body></html>'''
NO_DATA = ('<div id="ContentPlaceHolder1_ContentPlaceHolder1_DetallePlaceHolder_nodata">'
           '<p>Los datos aún no han sido publicados</p></div>')


def table(*rows):
    body = ''.join('<tr>' + ''.join(f'<td>{cell}</td>' for cell in row) + '</tr>'
                   for row in rows)
    return f'<table class="tabla"><tbody>{body}</tbody></table>'


class DeputyWebDriverLocatorsTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        options = webdriver.FirefoxOptions()
        options.add_argument('-headless')
        cls.driver = webdriver.Firefox(options=options)
        cls.pages_dir = tempfile.TemporaryDirectory()

    @classmethod
    def tearDownClass(cls):
        cls.driver.quit()
        cls.pages_dir.cleanup()

    def setUp(self):
        for collected in (dg_gastos.operational_costs,
                          dg_gastos.external_consultancies,
                          dg_gastos.support_staff):
            for values in collected.values():
                values.clear()

    def open_scraper_on(self, content: str) -> DeputyWebDriver:
        page = pathlib.Path(self.pages_dir.name, f'{self.id()}.html')
        page.write_text(PAGE.format(content=content), encoding='utf-8')
        with mock.patch.object(dg_gastos, 'FIRST_DIPUTY_URL', page.as_uri()):
            scraper = DeputyWebDriver(self.driver)
        scraper.current_deputy = 'Florcita Alarcón Rojas'
        scraper.current_year = 2021
        scraper.current_month_index = 3
        return scraper

    def test_reads_operational_costs_table(self):
        scraper = self.open_scraper_on(table(('TELEFONÍA', '$43.452'),
                                             ('TRASPASO DESDE GASTOS OPERACIONALES', '$1.000')))

        scraper.get_data_from_operational_costs_table()

        self.assertEqual(dg_gastos.operational_costs, {
            'diputado': ['Florcita Alarcón Rojas'] * 2,
            'Anio': [2021, 2021],
            'Mes': [3, 3],
            'Gastos': ['TELEFONÍA', 'TRASPASO DESDE GASTOS OPERACIONALES'],
            'Montos': ['$43.452', '$1.000'],
        })

    def test_opens_operational_costs_when_link_is_obscured(self):
        destination = pathlib.Path(self.pages_dir.name, 'gastosoperacionales.html')
        destination.write_text('<title>Gastos operacionales</title>', encoding='utf-8')
        scraper = self.open_scraper_on(f'''
            <a id="ContentPlaceHolder1_ContentPlaceHolder1_btGasop"
               href="{destination.name}#ficha-diputados">Gastos operacionales</a>
            <div id="ajax-container">
                <div style="position: relative; top: -2rem; height: 4rem;">Panel de detalle</div>
            </div>
        ''')

        scraper.get_into_operational_costs_section()

        self.assertEqual(self.driver.current_url, f'{destination.as_uri()}#ficha-diputados')
        self.assertEqual(self.driver.title, 'Gastos operacionales')

    def test_detects_month_without_published_data(self):
        scraper = self.open_scraper_on(NO_DATA)

        self.assertIs(scraper._fast_check_if_there_is_data_section(), False)

    def test_opens_and_reads_external_consultancies(self):
        scraper = self.open_scraper_on(
            table(('Ver', '12', '01/03/2021', 'Juan Pérez', 'Informe legislativo', '$822.400')))

        scraper.get_into_external_consultancies()
        scraper.get_data_from_external_consultancies()

        self.assertEqual(self.driver.title, 'asesorias')
        self.assertEqual(dg_gastos.external_consultancies['Asesor'], ['Juan Pérez'])
        self.assertEqual(dg_gastos.external_consultancies['Monto'], ['$822.400'])

    def test_reads_support_staff_table(self):
        scraper = self.open_scraper_on(
            table(('Personal de apoyo', '1', 'Ana Soto', 'Secretaria', '$1.200.000', 'No', '')))

        scraper.get_data_from_support_staff()

        self.assertEqual(dg_gastos.support_staff['Nombre'], ['Ana Soto'])
        self.assertEqual(dg_gastos.support_staff['Sueldo'], ['$1.200.000'])


if __name__ == '__main__':
    unittest.main()
