"""
Short script for using the same webdriver.
Gets the driver from the environment variables
in case you want to use this script in a container
or set it from a console.
"""

import os
from selenium import webdriver
from selenium.webdriver import Remote as RemoteWebDriver
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By

DEFAULT_DRIVER = 'firefox'
SUPPORTED_DRIVERS = ('chrome', 'firefox')


def get_driver() -> RemoteWebDriver:
    """
    Start the browser named by the DRIVER environment variable
    ('chrome' or 'firefox'), defaulting to Firefox when it is unset.
    """
    name = (os.getenv('DRIVER') or DEFAULT_DRIVER).strip().lower()

    if name == 'firefox':
        return webdriver.Firefox()
    if name == 'chrome':
        return webdriver.Chrome()

    raise ValueError(
        f"Unsupported DRIVER {name!r}; expected one of: {', '.join(SUPPORTED_DRIVERS)}"
    )


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