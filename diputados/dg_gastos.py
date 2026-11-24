"""
data getter: información de gastos de cada diputado
@Author: AlasAltum
"""
import logging
import re
import pandas as pd
import time
from selenium.webdriver import Remote as RemoteWebDriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select
from selenium.common.exceptions import (StaleElementReferenceException,
                                        TimeoutException,
                                        NoSuchWindowException,
                                        ElementClickInterceptedException)
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from driver_utils import get_driver, _by_css_selector, _by_xpath_selector, _by_id

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
NO_DATA_PARRAGRAPH_XPATH = '//div[@id="ContentPlaceHolder1_ContentPlaceHolder1_DetallePlaceHolder_nodata"]/p'
TABLE_ROW_XPATH = '//table[@class="tabla"]/tbody/tr'
DEPUTY_COST_TABLE_XPATH = '//table[@class="tabla"]/tbody'
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

    def get_into_operational_costs_section(self):
        """
        Open the operational-costs URL without relying on the page layout.
        """
        link = self.webdriver_wait.until(
            EC.presence_of_element_located((By.CSS_SELECTOR, OPERATIONAL_COSTS_CSS))
        )
        self.driver.get(link.get_property('href'))

    def get_and_update_current_year(self):
        """
        Gets the current year in the selector and select it as the current year
        """
        self._log('Obteniendo el año que aparece en la página...')
        current_year = self.webdriver_wait.until(_by_css_selector(YEAR_SELECTOR_CSS))
        # example: 2018\n2019\n2020\n2021
        # after map(int, example) -> [2018, 2019, 2020, 2021]
        self.available_years = list(map(int, current_year.text.split('\n')))
        # get the current year
        self.current_year = int(Select(current_year).first_selected_option.text)
        self._log(f'Año actual actualizado a: {self.current_year}')

    def get_and_update_current_month(self):
        self._log('Obteniendo el mes que aparece en la página...')
        dropdown = self.webdriver_wait.until(_by_css_selector(MONTH_SELECTOR_CSS))
        month = Select(dropdown).first_selected_option.text
        self.current_month_index = MONTH_TEXT_TO_NUMBER[month]
        self._log(f'Mes actual: {month}')


    def set_one_year_backward(self, *, wait_for_refresh=False):
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
                if wait_for_refresh:
                    self.webdriver_wait.until(EC.staleness_of(dropdown_year))
                    self.webdriver_wait.until(
                        lambda driver: driver.find_element(By.CSS_SELECTOR, YEAR_SELECTOR_CSS)
                        .get_property('value') == str(previous_year)
                    )
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

    def _select_month(self, *, last=False) -> bool:
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
                month_number = MONTH_TEXT_TO_NUMBER[month.text]
                if month != selected:
                    month.click()
                self.current_month_index = month_number
                return True
            except (ElementClickInterceptedException, StaleElementReferenceException) as exc:
                if attempt == MAX_MONTH_SELECTION_ATTEMPTS:
                    raise RuntimeError(
                        f'No se pudo seleccionar el mes tras {attempt} intentos (año {self.current_year})'
                    ) from exc

    def set_one_month_backward(self) -> bool:
        """Select the previous listed month or the last listed month of the previous year."""
        if not self.there_is_more_data_to_scrap:
            return False
        if self._select_month():
            return True
        return self.set_one_year_backward() and self._select_month(last=True)

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
                gasto_elements = self.driver.find_elements(By.XPATH, '//table[@class="tabla"]/tbody/tr/td[1]')
                monto_elements = self.driver.find_elements(By.XPATH, '//table[@class="tabla"]/tbody/tr/td[2]')

                gastos_text = [element.text for element in gasto_elements]
                monto_text = [element.text for element in monto_elements]

                for gasto, monto in zip(gastos_text, monto_text):
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
        """
        
        """
        external_consultancies_element = self.driver.find_element(By.ID, 'ContentPlaceHolder1_ContentPlaceHolder1_btnAsexterna')
        external_consultancies_element.click()


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
                xpath_prefix = '//table[@class="tabla"]/tbody/tr/td'
                try:
                    self.webdriver_wait.until(_by_xpath_selector(xpath_prefix + '[1]'))
                except TimeoutException:
                    if (self.driver.find_elements(By.XPATH, DEPUTY_COST_TABLE_XPATH)
                            and not self.driver.find_elements(By.XPATH, TABLE_ROW_XPATH)):
                        return
                    raise

                doc_elements = self.driver.find_elements(By.XPATH, xpath_prefix + '[1]')
                folio_elements = self.driver.find_elements(By.XPATH, xpath_prefix + '[2]')
                fecha_elements = self.driver.find_elements(By.XPATH, xpath_prefix + '[3]')
                asesor_elements = self.driver.find_elements(By.XPATH, xpath_prefix + '[4]')
                detalle_elements = self.driver.find_elements(By.XPATH, xpath_prefix + '[5]')
                monto_elements = self.driver.find_elements(By.XPATH, xpath_prefix + '[6]')
                # TODO: Agregar link documento
                doc_text = [element.text for element in doc_elements] # StaleElementReferenceException
                folio_text = [element.text for element in folio_elements]
                fecha_text = [element.text for element in fecha_elements]
                asesor_text = [element.text for element in asesor_elements]
                detalle_text = [element.text for element in detalle_elements]
                monto_text = [element.text for element in monto_elements]

                for doc, folio, fecha, asesor, detalle, monto in zip(
                        doc_text, folio_text, fecha_text, asesor_text, detalle_text, monto_text):
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
        LIST_CSS = '#ContentPlaceHolder1_ContentPlaceHolder1_btpeapo'
        supporting_staff_element = self.webdriver_wait.until(_by_css_selector(LIST_CSS))
        supporting_staff_element.click()
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
                # these XPATHS were the ones in the HTML for the following elements:
                tipo_elements = self.driver.find_elements(By.XPATH, '//table[@class="tabla"]/tbody/tr/td[1]')
                nombre_elements = self.driver.find_elements(By.XPATH, '//table[@class="tabla"]/tbody/tr/td[3]')
                cargo_elements = self.driver.find_elements(By.XPATH, '//table[@class="tabla"]/tbody/tr/td[4]')
                sueldo_elements = self.driver.find_elements(By.XPATH, '//table[@class="tabla"]/tbody/tr/td[5]')
                cargo_eleccion_elements = self.driver.find_elements(By.XPATH, '//table[@class="tabla"]/tbody/tr/td[6]')
                cese_funciones_elements = self.driver.find_elements(By.XPATH, '//table[@class="tabla"]/tbody/tr/td[7]')

                tipo_text = [element.text for element in tipo_elements]
                nombre_text = [element.text for element in nombre_elements]
                cargo_text = [element.text for element in cargo_elements]
                sueldo_text = [element.text for element in sueldo_elements]
                cargo_eleccion_text = [element.text for element in cargo_eleccion_elements]
                cese_funciones_text = [element.text for element in cese_funciones_elements]

                for tipo, nombre, cargo, sueldo, cargo_eleccion, cese in zip(
                    tipo_text, nombre_text, cargo_text, sueldo_text, cargo_eleccion_text, cese_funciones_text):
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

    def _reset_dates_for_another_section(self):
        self.get_and_update_current_year()
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
            webdriver.set_one_year_backward(wait_for_refresh=True)

        webdriver._log('Se terminaron de obtener los datos de asesorías externas de '
                       f'{current_deputy_name}, pasando a Personal de apoyo...')
        # get all supporting staff
        webdriver.get_into_supporting_staff()
        webdriver._reset_dates_for_another_section()
        while webdriver.there_is_more_data_to_scrap:
            webdriver.get_data_from_support_staff()
            webdriver.set_one_month_backward()

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
