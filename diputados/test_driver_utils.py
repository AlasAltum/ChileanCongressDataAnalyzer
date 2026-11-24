import os
import unittest
from unittest import mock

from selenium import webdriver

import driver_utils


class GetDriverTest(unittest.TestCase):

    def _get_driver_with_env(self, env):
        with mock.patch.dict(os.environ, env, clear=True), \
                mock.patch.object(webdriver, 'Firefox') as firefox, \
                mock.patch.object(webdriver, 'Chrome') as chrome:
            driver = driver_utils.get_driver()
        return driver, firefox, chrome

    def test_defaults_to_firefox_when_unset(self):
        driver, firefox, chrome = self._get_driver_with_env({})
        firefox.assert_called_once_with()
        chrome.assert_not_called()
        self.assertIs(driver, firefox.return_value)

    def test_driver_chrome(self):
        driver, firefox, chrome = self._get_driver_with_env({'DRIVER': 'chrome'})
        chrome.assert_called_once_with()
        firefox.assert_not_called()
        self.assertIs(driver, chrome.return_value)

    def test_driver_firefox(self):
        driver, firefox, chrome = self._get_driver_with_env({'DRIVER': 'firefox'})
        firefox.assert_called_once_with()
        chrome.assert_not_called()
        self.assertIs(driver, firefox.return_value)

    def test_driver_name_is_case_insensitive(self):
        driver, _, chrome = self._get_driver_with_env({'DRIVER': ' Chrome '})
        self.assertIs(driver, chrome.return_value)

    def test_unsupported_driver_raises_clear_error(self):
        with self.assertRaisesRegex(ValueError, r"Unsupported DRIVER 'safari'.*chrome, firefox"):
            self._get_driver_with_env({'DRIVER': 'safari'})


if __name__ == '__main__':
    unittest.main()
