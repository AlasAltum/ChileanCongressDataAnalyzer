"""
Short script for using the same webdriver.
Gets the driver from the environment variables
in case you want to use this script in a container
or set it from a console.
"""

import os
import selenium
from selenium.webdriver import Remote as RemoteWebDriver
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By


def get_driver() -> RemoteWebDriver:
    key = 'DRIVER'
    value = os.getenv(key) # Recover driver from environment variables
    driver = None

    if value == None:
        # set mozilla as default driver 
        DRIVER = 'mozilla'    

        if DRIVER == 'mozilla':
            # Es posible que tengan que indicar un path: 
            driver = selenium.webdriver.Firefox()

        elif DRIVER == 'chrome':
            driver = selenium.webdriver.Chrome()

    return driver


def _by_id(id_of_html_element: str):
    """
    Wrapper for expected_conditions.element_to_be_clickable method
    when searching by id of an element
    """
    return EC.element_to_be_clickable((By.ID, id_of_html_element))

def _by_css_selector(name_css: str):
    """
    Wrapper for expected_conditions.element_to_be_clickable method
    when searching by CSS Selector
    """
    return EC.element_to_be_clickable((By.CSS_SELECTOR, name_css))

def _by_xpath_selector(xpath: str):
    """
    Wrapper for expected_conditions.element_to_be_clickable method
    when searching by XPATH Selector
    """
    return EC.element_to_be_clickable((By.XPATH, xpath))