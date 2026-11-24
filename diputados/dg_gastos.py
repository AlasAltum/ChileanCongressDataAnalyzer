"""
data getter: información de gastos de cada diputado
@Author: AlasAltum
"""
import logging
import re
import pandas as pd
import time
from urllib.parse import parse_qsl, urlencode, urlsplit
from selenium.webdriver import Remote as RemoteWebDriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select
from selenium.common.exceptions import (StaleElementReferenceException,
                                        TimeoutException,
                                        NoSuchWindowException,
                                        ElementClickInterceptedException)
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from driver_utils import get_driver, _by_css_selector, _by_id

THERE_IS_TABLE = 0
THERE_IS_NO_TABLE_BUT_TEXT = 1
NEED_TO_RELOAD = 2

DRIVER = 'mozilla'  # Aquí se tiene que entregar el driver de chrome o mozzilla
FIRST_DIPUTY_URL = 'https://www.camara.cl/diputados/detalle/gastosoperacionales.aspx?prmId=1008#ficha-diputados'
DIPUTY_SELECTOR_CSS = '#ContentPlaceHolder1_ContentPlaceHolder1_ddlDiputados'
YEAR_SELECTOR_CSS = '#ContentPlaceHolder1_ContentPlaceHolder1_DetallePlaceHolder_ddlAno'
MONTH_SELECTOR_CSS = '#ContentPlaceHolder1_ContentPlaceHolder1_DetallePlaceHolder_ddlMes'
MAX_MONTH_SELECTION_ATTEMPTS = 3
DEPUTIES_DROPDOWN_ID = 'ContentPlaceHolder1_ContentPlaceHolder1_ddlDiputados'
CURRENT_YEAR_CSS = 'ContentPlaceHolder1_ContentPlaceHolder1_DetallePlaceHolder_ddlAno'
OPERATIONAL_COSTS_CSS = '#ContentPlaceHolder1_ContentPlaceHolder1_btGasop'
EXTERNAL_CONSULTANCIES_CSS = '#ContentPlaceHolder1_ContentPlaceHolder1_btnAsexterna'
SUPPORT_STAFF_CSS = '#ContentPlaceHolder1_ContentPlaceHolder1_btpeapo'
NO_DATA_PARRAGRAPH_XPATH = '//div[@id="ContentPlaceHolder1_ContentPlaceHolder1_DetallePlaceHolder_nodata"]/p'
TABLE_ROW_XPATH = '//table[@class="tabla"]/tbody/tr'
DEPUTY_COST_TABLE_XPATH = '//table[@class="tabla"]/tbody'
TOP_LEVEL_COST_TABLE_XPATH = '//table[@class="tabla" and not(ancestor::table[@class="tabla"])]/tbody'
EMPTY_CONSULTANCIES_XPATH = (
    '//*[@id="ajax-container"]//div[@id="body" and @class="table-responsive"'
    ' and not(*) and not(normalize-space())]'
    '[../div[@class="top-tabs-sesiones"]/h4[normalize-space()="Asesorías Externas"]]'
)
MONTHS = (
    'Todos', # This one appears only in some cases.
    'enero',
    'febrero',
    'marzo',
    'abril',
    'mayo',
    'junio',
    'julio',
    'agosto',
    'septiembre',
    'octubre',
    'noviembre',
    'diciembre',
)
MONTH_TEXT_TO_NUMBER = {
    'Todos': 0,
    'enero': 1,
    'febrero': 2,
    'marzo': 3,
    'abril': 4,
    'mayo': 5,
    'junio': 6,
    'julio': 7,
    'agosto': 8,
    'septiembre': 9,
    'octubre': 10,
    'noviembre': 11,
    'diciembre': 12,
}
WAITING_TIME = 2
# Year changes post the whole form; camara.cl took ~45 s to answer one.
POSTBACK_TIMEOUT = 120


def _month_number(label):
    return MONTH_TEXT_TO_NUMBER[label if label in MONTH_TEXT_TO_NUMBER else label.lower()]


operational_costs = {
        'diputado': [],
        'Anio': [],
        'Mes': [],
        'Gastos': [],
        'Montos': [],
    }

external_consultancies = {
        'Diputado': [],
        'Anio': [],
        'Doc': [],
        'Folio': [],
        'Fecha': [],
        'Asesor': [],
        'Detalle': [],
        'Monto': [],
    }

support_staff = {
    'Diputado': [],
    'Anio': [],
    'Mes': [],
    'Tipo': [],
    'Nombre': [],
    'Cargo': [],
    'Sueldo': [],
    'Cargo Elección (Servel)': [],
    'Cese de Funciones': [],
}

# TODO: add party to each current deputy
# logger = logging.getLogger(name='DeputyLogger')
# logger.setLevel(logging.DEBUG)
# handler = logging.StreamHandler(sys.stdout)
# handler.setLevel(logging.DEBUG)
# logger.addHandler(handler)


class DeputyWebDriver:
    """
    Class for scrapping data from chilean deputies
    using the page: https://www.camara.cl/diputados/
    """
    def __init__(self, _webdriver: RemoteWebDriver, logger_name='DeputyLogger'):
        self.driver : RemoteWebDriver = _webdriver
        self.webdriver_wait : WebDriverWait = WebDriverWait(_webdriver, WAITING_TIME)
        self.postback_wait : WebDriverWait = WebDriverWait(_webdriver, POSTBACK_TIMEOUT)
        self.current_deputy = ''
        self.current_month_index = 12  # initializes in december
        self.current_year = 2021
        self.available_years = []
        self.there_is_more_data_to_scrap = True
        # self.logger = None
        self.driver.get(FIRST_DIPUTY_URL)

    def _log(self, log_msg : str):
        """
        Log the phase the scraper is on by using the logger
        """
        # self.logger.log(level=0,msg=log_msg)
        print(log_msg)

    def get_deputies_from_dropdown(self) -> list[tuple[str, str]]:
        self._log('Obteniendo nombres de los diputados.')
        deputies_dropdown = self.webdriver_wait.until(_by_id(DEPUTIES_DROPDOWN_ID))
        deputies = self.driver.execute_script(
            'return Array.from(arguments[0].options, option => [option.text, option.value]);',
            deputies_dropdown)
        self._log(f'Se obtuvieron {len(deputies)} nombres.')
        return [tuple(deputy) for deputy in deputies]


    def _handle_select_to_change_deputy(self, deputy_id: str):
        """
        When changing between deputies, sometimes appear some
        exceptions, so we need to repeat them
        """
        try:
            deputies_dropdown = self.webdriver_wait.until(_by_id(DEPUTIES_DROPDOWN_ID))
            Select(deputies_dropdown).select_by_value(deputy_id)

        # If we have an error, repeat after some time
        except ElementClickInterceptedException:
            self.driver.refresh()
            TIME_TO_AVOID_CLICK_INTERCEPTION = 2.0
            time.sleep(TIME_TO_AVOID_CLICK_INTERCEPTION)
            
            return self._handle_select_to_change_deputy(deputy_id)

    def get_deputy_name(self) -> str:
        """
        Gets the name of a given deputy from the page
        """
        self._log('Obteniendo nombre del siguiente diputado...')
        name_css = '.rotulo' 
        # example: Diputado Florcita Alarcón Rojas
        name = self.webdriver_wait.until(_by_css_selector(name_css))
         # remove prefix Diputado or Diputada
        name_without_prefix = re.sub(pattern=r'Diputad[oa] ', repl='', string=name.text)
        self.current_deputy = name_without_prefix
        self._log(f'Nombre del diputado cuyos datos se extraen: {self.current_deputy}')
        return name_without_prefix

    def _open_deputy_section(self, link_css: str) -> str:
        """
        Open a section link for the deputy shown on the page, without relying
        on the page layout. After a month or year postback camara.cl renders
        these links with a literal prmId={0}, so the deputy id comes from the
        page URL instead of the link.
        """
        link = self.webdriver_wait.until(
            EC.presence_of_element_located((By.CSS_SELECTOR, link_css))
        )
        page_query = parse_qsl(urlsplit(self.driver.current_url).query)
        deputy_id = {key.lower(): value for key, value in page_query}['prmid']
        section_url = urlsplit(link.get_property('href'))._replace(
            query=urlencode({'prmId': deputy_id}))
        target_url = section_url.geturl()
        self.driver.get(target_url)
        return target_url

    def get_into_operational_costs_section(self):
        self._open_deputy_section(OPERATIONAL_COSTS_CSS)

    def get_and_update_current_year(self, *, select_latest=False):
        """Read the available years and optionally select the newest one."""
        self._log('Obteniendo el año que aparece en la página...')
        find_year_dropdown = _by_css_selector(YEAR_SELECTOR_CSS)

        def read_year(driver):
            try:
                dropdown = find_year_dropdown(driver)
                if not dropdown:
                    return False
                year_select = Select(dropdown)
                years = [int(option.text) for option in year_select.options]
                selected_year = int(year_select.first_selected_option.text)
                return dropdown, years, selected_year
            except StaleElementReferenceException:
                return False

        dropdown, years, selected_year = self.webdriver_wait.until(read_year)
        if select_latest:
            latest_year = max(years)
            if selected_year != latest_year:
                Select(dropdown).select_by_visible_text(str(latest_year))
                self._wait_for_postback(dropdown)
                _, years, selected_year = self.webdriver_wait.until(read_year)
                if selected_year != latest_year:
                    raise ValueError(f'La página cargó el año {selected_year} en vez de {latest_year}')
        self.available_years, self.current_year = years, selected_year
        self._log(f'Año actual actualizado a: {self.current_year}')

    def get_and_update_current_month(self):
        self._log('Obteniendo el mes que aparece en la página...')
        dropdown = self.webdriver_wait.until(_by_css_selector(MONTH_SELECTOR_CSS))
        month = Select(dropdown).first_selected_option.text
        self.current_month_index = _month_number(month)
        self._log(f'Mes actual: {month}')

    def _wait_for_postback(self, element_on_previous_page) -> None:
        """Wait until the page holding the element is replaced and fully loaded."""
        self.postback_wait.until(
            lambda driver: EC.staleness_of(element_on_previous_page)(driver)
            and driver.execute_script('return document.readyState') == 'complete'
        )

    def set_one_year_backward(self):
        """
        Set scroller of years one year in the past by moving the selector.
        """
        # TODO: Check if CSS is different in
        current_year = self.current_year
        previous_year = current_year - 1
        self._log(f'Cambiando al año anterior: Año actual {current_year}')
        try:
            dropdown_year = self.webdriver_wait.until(_by_css_selector(YEAR_SELECTOR_CSS))
            dropdown_year_select = Select(dropdown_year)
            # if previous_year has available data:
            if previous_year in self.available_years:
                dropdown_year_select.select_by_visible_text(str(previous_year))
                self._wait_for_postback(dropdown_year)
                loaded_year = Select(self.webdriver_wait.until(_by_css_selector(YEAR_SELECTOR_CSS)))\
                    .first_selected_option.text
                if loaded_year != str(previous_year):
                    raise ValueError(f'La página cargó el año {loaded_year}')
                self.get_and_update_current_month()
                self.current_year = previous_year
                self._log(f'Se restó un año satisfactoriamente, año actual: {self.current_year}')
                return True
            else:  # Case we reach a year without data
                self.there_is_more_data_to_scrap = False
                self._log(f'No hay datos del {previous_year}...')
                return False
        except NoSuchWindowException:
            raise
        except Exception as e:
            raise RuntimeError(f'No se pudo cambiar del año {current_year} al año {previous_year}') from e

    def _select_month(self, *, last=False, wait_for_refresh=False) -> bool:
        for attempt in range(1, MAX_MONTH_SELECTION_ATTEMPTS + 1):
            try:
                dropdown = self.webdriver_wait.until(_by_css_selector(MONTH_SELECTOR_CSS))
                month_select = Select(dropdown)
                options = month_select.options
                selected = month_select.first_selected_option
                position = len(options) - 1 if last else options.index(selected) - 1
                if position < 0:
                    return False

                month = options[position]
                month_number = _month_number(month.text)
                if month != selected:
                    month.click()
                    if wait_for_refresh:
                        self._wait_for_postback(dropdown)
                        refreshed_dropdown = self.webdriver_wait.until(_by_css_selector(MONTH_SELECTOR_CSS))
                        loaded_month = Select(refreshed_dropdown).first_selected_option.text
                        if _month_number(loaded_month) != month_number:
                            raise ValueError(f'La página cargó {loaded_month} en vez de {MONTHS[month_number]}')
                self.current_month_index = month_number
                return True
            except (ElementClickInterceptedException, StaleElementReferenceException) as exc:
                if attempt == MAX_MONTH_SELECTION_ATTEMPTS:
                    raise RuntimeError(
                        f'No se pudo seleccionar el mes tras {attempt} intentos (año {self.current_year})'
                    ) from exc

    def set_one_month_backward(self, *, wait_for_refresh=False) -> bool:
        """Select the previous listed month or the last listed month of the previous year."""
        if not self.there_is_more_data_to_scrap:
            return False
        if self._select_month(wait_for_refresh=wait_for_refresh):
            return True
        return self.set_one_year_backward() and self._select_month(
            last=True, wait_for_refresh=wait_for_refresh)

    def _fast_check_if_there_is_data_section(self, *, empty_panel_xpath=None) -> bool:
        """Wait for the data table or a recognized no-data state."""
        def find_data_section(driver):
            if driver.find_elements(By.XPATH, DEPUTY_COST_TABLE_XPATH):
                return 'table'
            notices = driver.find_elements(By.XPATH, NO_DATA_PARRAGRAPH_XPATH)
            if any('no han sido publicados' in notice.text for notice in notices):
                return 'no_data'
            if empty_panel_xpath and driver.find_elements(By.XPATH, empty_panel_xpath):
                return 'no_data'
            return None

        section = self.webdriver_wait.until(
            find_data_section,
            f'No se encontró tabla ni aviso de datos no publicados para '
            f'{self.current_deputy}, {MONTHS[self.current_month_index]} de {self.current_year}',
        )
        return section == 'table'

    def _read_table_cells(self, section, width, *, allow_unlabelled_column=False):
        bodies = self.driver.find_elements(By.XPATH, TOP_LEVEL_COST_TABLE_XPATH)
        tables = self.driver.execute_script("""
            return arguments[0].map(body => ({
                headers: Array.from(body.parentElement.tHead?.rows[0]?.cells ?? []),
                rows: Array.from(body.rows, row => {
                    const cells = Array.from(row.cells);
                    return [cells, cells.filter(cell => cell.localName === 'td').length];
                }),
            }));
        """, bodies)
        rows = []
        for table in tables:
            expected = width
            if allow_unlabelled_column:
                headers = table['headers']
                if len(headers) == width + 1 and not headers[-1].text.strip():
                    expected = width + 1

            for row_number, (cells, data_count) in enumerate(table['rows'], start=1):
                if len(cells) != expected or data_count != expected:
                    raise ValueError(
                        f'{section}: {self.current_deputy}, '
                        f'{MONTHS[self.current_month_index]} de {self.current_year}, '
                        f'fila {row_number}: se esperaban {expected} celdas td, '
                        f'se encontraron {len(cells)} celdas ({data_count} td)'
                    )
                rows.append([cell.text for cell in cells[:width]])
        return rows


    def get_data_from_operational_costs_table(self) -> None:
        """
        Gets data from operational costs table and adds it to
        operational_costs, including current deputy, year, month
        and the data displayed
        Format:
        Gastos: str 	Monto: int 
        """
        if not (1 <= self.current_month_index <= 12):
            # do not get information for month "Todos", because it is not
            # possible in this section.
            return

        try:
            available_data = self._fast_check_if_there_is_data_section()
            if available_data is False:
                self._log(f'Mes {MONTHS[self.current_month_index]} del año '
                  f'{self.current_year} no tiene datos. Saltando...')

            if available_data:
                for gasto, monto in self._read_table_cells(
                        'Costos operacionales', 2, allow_unlabelled_column=True):
                    operational_costs['diputado'].append(self.current_deputy)
                    operational_costs['Anio'].append(self.current_year)
                    operational_costs['Mes'].append(self.current_month_index)
                    operational_costs['Gastos'].append(gasto)
                    operational_costs['Montos'].append(monto)

                self._log('Se agregaron datos de costos operacionales para el mes '
                          f'{MONTHS[self.current_month_index]} satisfactoriamente')

        except StaleElementReferenceException:
            self.get_data_from_operational_costs_table()


    def select_all_months_in_month_dropwdown(self) -> None:
        """
        In the section external consultancies, there is an option
        'Todos' in the dropdown element, where all consultancies
        for a given year are displayed.
        This function locates the dropdown element and selects
        'Todos'
        """
        try:
            dropdown_month = self.webdriver_wait.until(_by_css_selector(MONTH_SELECTOR_CSS))
            dropdown_month_select = Select(dropdown_month)
            month = dropdown_month_select.options[0].text
            dropdown_month_select.select_by_index(0)
            self.current_month_index = MONTH_TEXT_TO_NUMBER[month]
        except StaleElementReferenceException:
            self.select_all_months_in_month_dropwdown()

    def get_into_external_consultancies(self) -> None:
        self._open_deputy_section(EXTERNAL_CONSULTANCIES_CSS)


    def get_data_from_external_consultancies(self) -> None:
        """
        Get the data from external consultancies of a deputy during a whole year
        """
        try:
            available_data = self._fast_check_if_there_is_data_section(
                empty_panel_xpath=EMPTY_CONSULTANCIES_XPATH,
            )
            if available_data is False:
                self._log(f'Mes {MONTHS[self.current_month_index]} del año '
                  f'{self.current_year} no tiene datos. Saltando...')

            if available_data:
                try:
                    self.webdriver_wait.until(EC.presence_of_element_located((By.XPATH, TABLE_ROW_XPATH)))
                except TimeoutException:
                    if (self.driver.find_elements(By.XPATH, DEPUTY_COST_TABLE_XPATH)
                            and not self.driver.find_elements(By.XPATH, TABLE_ROW_XPATH)):
                        return
                    raise

                # TODO: Agregar link documento
                for doc, folio, fecha, asesor, detalle, monto in self._read_table_cells('Asesorías externas', 6):
                    external_consultancies['Diputado'].append(self.current_deputy)
                    external_consultancies['Anio'].append(self.current_year)
                    external_consultancies['Doc'].append(doc)
                    external_consultancies['Folio'].append(folio)
                    external_consultancies['Fecha'].append(fecha)
                    external_consultancies['Asesor'].append(asesor)
                    external_consultancies['Detalle'].append(detalle)
                    external_consultancies['Monto'].append(monto)

                self._log('Se obtuvieron los datos de las asesorías externas para el año '
                          f'{self.current_year} y el mes {MONTHS[self.current_month_index]}')
        except StaleElementReferenceException:
            # This might happen when changes were made too fast
            self.get_data_from_external_consultancies()


    def get_into_supporting_staff(self) -> bool:
        """Open the supporting staff section for the current deputy."""
        staff_url = self._open_deputy_section(SUPPORT_STAFF_CSS)
        staff_path = urlsplit(staff_url).path
        if urlsplit(self.driver.current_url).path != staff_path:
            self.driver.get(staff_url)
            if urlsplit(self.driver.current_url).path != staff_path:
                raise RuntimeError(f'No se pudo abrir Personal de apoyo: {self.driver.current_url}')
        return True


    def get_data_from_support_staff(self):
        """
        
        """
        if not (1 <= self.current_month_index <= 12):
            # do not get information for month "Todos", because it is not
            # possible in this section.
            return

        try:
            available_data = self._fast_check_if_there_is_data_section()
            if available_data is False:
                self._log(f'Mes {MONTHS[self.current_month_index]} del año '
                  f'{self.current_year} no tiene datos. Saltando...')

            if available_data:
                for tipo, _, nombre, cargo, sueldo, cargo_eleccion, cese in self._read_table_cells(
                        'Personal de apoyo', 7):
                    support_staff['Diputado'].append(self.current_deputy)
                    support_staff['Anio'].append(self.current_year)
                    support_staff['Mes'].append(self.current_month_index)
                    support_staff['Tipo'].append(tipo)
                    support_staff['Nombre'].append(nombre)
                    support_staff['Cargo'].append(cargo)
                    support_staff['Sueldo'].append(sueldo)
                    support_staff['Cargo Elección (Servel)'].append(cargo_eleccion)
                    support_staff['Cese de Funciones'].append(cese)

                self._log(f'Se obtuvieron datos de personal de apoyo para el mes '
                          f'{MONTHS[self.current_month_index]} del año {self.current_year}')

        except StaleElementReferenceException:
            self.get_data_from_support_staff()  # Just reload

    def _reset_dates_for_another_section(self, *, start_at_latest=False):
        self.get_and_update_current_year(select_latest=start_at_latest)
        if start_at_latest:
            self._select_month(last=True, wait_for_refresh=True)
        else:
            self.get_and_update_current_month()
        self.there_is_more_data_to_scrap = True


def _scrape_deputies(driver: RemoteWebDriver) -> None:
    webdriver = DeputyWebDriver(driver)
    deputies = webdriver.get_deputies_from_dropdown()
    deputies_collected_data  = set()

    # Do this for every deputy, since we know all the names
    # We know we should have data for every deputy    
    while len(deputies_collected_data) < len(deputies):
        _, deputy_id = deputies[len(deputies_collected_data)]
        webdriver._handle_select_to_change_deputy(deputy_id)
        current_deputy_name = webdriver.get_deputy_name()

        # get all operational costs
        webdriver.get_into_operational_costs_section()
        webdriver._reset_dates_for_another_section()
        while webdriver.there_is_more_data_to_scrap: 
            webdriver.get_data_from_operational_costs_table()
            webdriver.set_one_month_backward()
        
        webdriver._log('Se terminó de obtener costos operacionales de '
                       f'{current_deputy_name}, pasando a asesorías externas...')
        # get all external consultancies
        webdriver.get_into_external_consultancies()
        webdriver._reset_dates_for_another_section()
        # This section has the value "Todos" in its dropdown which allows us
        # to see all data in a whole year, therefore, we select
        # all months at once in the month dropdown and advance per year
        while webdriver.there_is_more_data_to_scrap:
            webdriver.select_all_months_in_month_dropwdown()
            webdriver.get_data_from_external_consultancies()
            webdriver.set_one_year_backward()

        webdriver._log('Se terminaron de obtener los datos de asesorías externas de '
                       f'{current_deputy_name}, pasando a Personal de apoyo...')
        # get all supporting staff
        webdriver.get_into_supporting_staff()
        webdriver._reset_dates_for_another_section(start_at_latest=True)
        while webdriver.there_is_more_data_to_scrap:
            webdriver.get_data_from_support_staff()
            webdriver.set_one_month_backward(wait_for_refresh=True)

        deputies_collected_data.add(current_deputy_name)

        webdriver._log('Se terminaron de obtener datos de: '
                       f'{current_deputy_name}. Seguimos con...')


def main():
    driver = get_driver()
    try:
        _scrape_deputies(driver)
    finally:
        try:
            driver.quit()
        except Exception:
            logging.getLogger(__name__).exception('No se pudo cerrar el navegador')


if __name__ == "__main__":
    try:
        main()

        operational_costs_df = pd.DataFrame.from_dict(operational_costs)
        operational_costs_df.to_csv('collected_data/CostosOperacionales.csv', index=False)

        # change format of text to avoid int truncation
        # if we not apply this, values like: 
        #  '$822.400   ' will be passed as 822.4
        monto_to_int = lambda x: int(re.sub(r'[$.\s]', '', x))
        external_consultancies['Monto'] = [monto_to_int(monto) for monto in  external_consultancies['Monto']] 
        external_consultancies_df = pd.DataFrame.from_dict(external_consultancies)
        external_consultancies_df.to_csv('collected_data/ConsultoriasExternas.csv', index=False)

        support_staff['Sueldo'] = [monto_to_int(num) for num in support_staff['Sueldo']]
        # Export collected data to a csv file
        support_staff_df = pd.DataFrame.from_dict(support_staff)
        support_staff_df.to_csv('collected_data/SupportStaff.csv', index=False)

    except NoSuchWindowException:
        print('Se cerró el navegador')
        raise
