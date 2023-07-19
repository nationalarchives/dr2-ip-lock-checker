import os
import unittest
from unittest.mock import Mock

from urllib3.exceptions import ConnectTimeoutError

from lambda_function import get_response, BaseHTTPResponse, Website, verify_responses, print_error_message, \
    get_websites_with_errors, print_success_message, lambda_handler


def generate_list_of_websites():
    return {
        "Preservica_mock_website": Website(
            "Preservica_mock_website",
            "https://mockPreservicaWebsite.net",
            ConnectTimeoutError(),
            False,
            None
        ),
        "website2": Website("website2", "https://mockWebsite2.com", 200, False, None),
        "website3": Website("website3", "https://mockWebsite3.com", 200, False, None)
    }


class TestNotificationsLambda(unittest.TestCase):
    def test_get_response_should_return_200_status(self):
        http = Mock()
        response = BaseHTTPResponse()
        response.status = 200
        http.request = Mock(
            return_value = response
        )

        http_status: int | Exception = get_response(http.request, "https://mockWebhookUrl.com")

        assert http.request.call_args[0] == ("GET", "https://mockWebhookUrl.com")
        assert http.request.call_args[1]["timeout"].connect_timeout == 5
        assert not http.request.call_args[1]["retries"]
        assert http_status == 200

    def test_get_response_should_return_exception(self):
        http = Mock()
        http.request = Mock(side_effect = ConnectTimeoutError())

        http_status: int | Exception = get_response(http.request, "https://mockWebhookUrl.com")

        with self.assertRaises(Exception) as _:
            http.request()

        self.assertEqual(type(http_status), ConnectTimeoutError)

    def test_verify_response_should_return_a_received_expected_response_of_true_and_updated_actual_values(self):
        http = Mock()
        response = BaseHTTPResponse()
        response.status = 200
        http.request = Mock()
        http.request.side_effect = [ConnectTimeoutError(), response, response]

        initial_list_of_websites = generate_list_of_websites()

        expected_website_result = {
            "Preservica_mock_website": Website(
                "Preservica_mock_website",
                "https://mockPreservicaWebsite.net",
                ConnectTimeoutError(),
                True,
                str(ConnectTimeoutError())
            ),
            "website2": Website("website2", "https://mockWebsite2.com", 200, True, "200"),
            "website3": Website("website3", "https://mockWebsite3.com", 200, True, "200")
        }

        response = verify_responses(initial_list_of_websites, request = http.request)

        for website_name in ["Preservica_mock_website", "website2", "website3"]:
            self.assertEqual(response[website_name].url, expected_website_result[website_name].url)
            self.assertEqual(str(response[website_name].expected_response), str(expected_website_result[
                                                                                    website_name].expected_response))
            self.assertEqual(response[website_name].actual_response,
                             expected_website_result[website_name].actual_response)
            self.assertEqual(response[website_name].received_expected_response,
                             expected_website_result[website_name].received_expected_response)

    def test_verify_response_should_return_a_received_expected_response_of_false_and_updated_actual_values(self):
        http = Mock()
        response = BaseHTTPResponse()
        response.status = 200
        http.request = Mock()
        http.request.side_effect = [response, response, response]

        initial_list_of_websites = generate_list_of_websites()

        expected_website_result = {
            "Preservica_mock_website": Website(
                "Preservica_mock_website",
                "https://mockPreservicaWebsite.net",
                ConnectTimeoutError(),
                False,
                str(200)
            ),
            "website2": Website("website2", "https://mockWebsite2.com", 200, True, "200"),
            "website3": Website("website3", "https://mockWebsite3.com", 200, True, "200")
        }

        response = verify_responses(initial_list_of_websites, request = http.request)

        for website_name in ["Preservica_mock_website", "website2", "website3"]:
            self.assertEqual(response[website_name].url, expected_website_result[website_name].url)
            self.assertEqual(str(response[website_name].expected_response), str(expected_website_result[
                                                                                    website_name].expected_response))
            self.assertEqual(response[website_name].actual_response,
                             expected_website_result[website_name].actual_response)
            self.assertEqual(response[website_name].received_expected_response,
                             expected_website_result[website_name].received_expected_response)

    def test_verify_response_should_throw_an_error_if_unexpected_response(self):
        http = Mock()
        response = BaseHTTPResponse()
        response.status = 200
        http.request = Mock()

        initial_list_of_websites = generate_list_of_websites()
        initial_list_of_websites["Preservica_mock_website"].expected_response = 42.0

        with self.assertRaises(ValueError) as _:
            verify_responses(initial_list_of_websites, request = http.request)

    def test_print_error_message_should_print_error_message(self):
        mock_print = Mock()
        response = BaseHTTPResponse()
        response.status = 200

        websites = {
            "website2": Website(
                "website2", "https://mockWebsite2.com", 200, False, str(InterruptedError("an InterruptedError"))
            ),
            "website3": Website(
                "website3", "https://mockWebsite3.com", 200, False, str(InterruptedError("another InterruptedError"))
            )
        }

        print_error_message(websites, mock_print)

        expected_and_actual_responses = [("website2", "200", "an InterruptedError"), ("website3", "200",
                                                                                      "another InterruptedError")]

        for n, (name, expected, actual) in enumerate(expected_and_actual_responses):
            print(mock_print.call_args_list)
            self.assertEqual(
                mock_print.call_args_list[n].args[0],
                {"Status": "Failure",
                 "Website": name,
                 "Message": "This address is unexpectedly available",
                 "Expected Response": expected,
                 "Actual Response": actual
                 }
            )

    def test_print_success_message_should_print_success_message(self):
        mock_print = Mock()
        response = BaseHTTPResponse()
        response.status = 200

        preservica_website = Website(
            "Preservica_mock_website",
            "https://mockPreservicaWebsite.net",
            ConnectTimeoutError("timeout error"),
            True,
            ConnectTimeoutError("")
        )

        print_success_message(preservica_website, mock_print)

        self.assertEqual(
            mock_print.call_args_list[0].args[0],
            {"Status": "Success",
             "Website": "Preservica_mock_website",
             "Message": "Preservica_mock_website returned an expected response: timeout error"
             }
        )

    def test_get_websites_with_errors_should_return_0_websites_with_errors(self):
        websites = {
            "Preservica_mock_website": Website(
                "Preservica_mock_website",
                "https://mockPreservicaWebsite.net",
                ConnectTimeoutError(""),
                True,
                str(ConnectTimeoutError(""))
            ),
            "website2": Website("website2", "https://mockWebsite2.com", 200, True, "200"),
            "website3": Website("website3", "https://mockWebsite3.com", 200, True, "200")
        }

        preservica_website = websites.pop("Preservica_mock_website")

        websites_with_errors = get_websites_with_errors(preservica_website, websites)

        self.assertEqual(websites_with_errors, {})

    def test_get_websites_with_errors_should_return_preservica_website(self):
        websites = {
            "Preservica_mock_website": Website(
                "Preservica_mock_website",
                "https://mockPreservicaWebsite.net",
                str(ConnectTimeoutError("")),
                False,
                "200"
            ),
            "website2": Website("website2", "https://mockWebsite2.com", 200, True, "200"),
            "website3": Website("website3", "https://mockWebsite3.com", 200, True, "200")
        }
        preservica_website = websites.pop("Preservica_mock_website")

        websites_with_errors = get_websites_with_errors(preservica_website, websites)

        self.assertEqual(websites_with_errors["Preservica_mock_website"].url, "https://mockPreservicaWebsite.net")
        self.assertEqual(websites_with_errors["Preservica_mock_website"].expected_response,
                         str(ConnectTimeoutError("")))
        self.assertEqual(websites_with_errors["Preservica_mock_website"].received_expected_response, False)
        self.assertEqual(websites_with_errors["Preservica_mock_website"].actual_response, "200")

    def test_get_websites_with_errors_should_return_1_other_website_with_errors(self):
        websites = {
            "Preservica_mock_website": Website(
                "Preservica_mock_website",
                "https://mockPreservicaWebsite.net",
                ConnectTimeoutError(""),
                True,
                str(ConnectTimeoutError(""))
            ),
            "website2": Website("website2", "https://mockWebsite2.com", 200, False, str(InterruptedError())),
            "website3": Website("website3", "https://mockWebsite3.com", 200, True, "200")
        }

        preservica_website = websites.pop("Preservica_mock_website")

        websites_with_errors = get_websites_with_errors(preservica_website, websites)

        self.assertEqual(websites_with_errors["website2"].url, "https://mockWebsite2.com")
        self.assertEqual(websites_with_errors["website2"].expected_response, 200)
        self.assertEqual(websites_with_errors["website2"].received_expected_response, False)
        self.assertEqual(websites_with_errors["website2"].actual_response, str(InterruptedError()))

    def test_lambda_handler_should_call_print_success_message(self):
        os.environ["PRESERVICA_URL"] = "https://mockPreservicaWebsite.net"

        tested_websites_with_responses = {
            "Preservica": Website(
                "Preservica",
                "https://mockPreservicaWebsite.net",
                ConnectTimeoutError("expected response"),
                True,
                str(ConnectTimeoutError("expected response"))
            ),
            "website2": Website("website2", "https://mockWebsite2.com", 200, True, "200"),
            "website3": Website("website3", "https://mockWebsite3.com", 200, True, "200")
        }

        verify_responses_func = Mock(
            return_value = tested_websites_with_responses
        )

        print_success_message_func = Mock()

        lambda_handler(verify_responses_func, print_success_message_func=print_success_message_func)

        website = print_success_message_func.call_args_list[0].args[0]

        self.assertEqual(website.name, "Preservica")
        self.assertEqual(website.url, "https://mockPreservicaWebsite.net")
        self.assertEqual(str(website.expected_response), "expected response")
        self.assertEqual(website.received_expected_response, True)
        self.assertEqual(str(website.actual_response), "expected response")

    def test_lambda_handler_should_call_print_error_message_with_preservica_website(self):
        os.environ["PRESERVICA_URL"] = "https://mockPreservicaWebsite.net"

        tested_websites_with_responses = {
            "Preservica": Website(
                "Preservica",
                "https://mockPreservicaWebsite.net",
                ConnectTimeoutError("expected response"),
                False,
                "200"
            ),
            "website2": Website("website2", "https://mockWebsite2.com", 200, True, "200"),
            "website3": Website("website3", "https://mockWebsite3.com", 200, True, "200")
        }

        verify_responses_func = Mock(
            return_value = tested_websites_with_responses
        )

        print_error_message_func = Mock()

        lambda_handler(verify_responses_func, print_error_message_func=print_error_message_func)

        website = print_error_message_func.call_args_list[0].args[0]
        print(website)

        self.assertEqual(website["Preservica"].name, "Preservica")
        self.assertEqual(website["Preservica"].url, "https://mockPreservicaWebsite.net")
        self.assertEqual(str(website["Preservica"].expected_response), "expected response")
        self.assertEqual(website["Preservica"].received_expected_response, False)
        self.assertEqual(str(website["Preservica"].actual_response), "200")

    def test_lambda_handler_should_call_print_error_message_with_other_websites(self):
        os.environ["PRESERVICA_URL"] = "https://mockPreservicaWebsite.net"

        tested_websites_with_responses = {
            "Preservica": Website(
                "Preservica",
                "https://mockPreservicaWebsite.net",
                ConnectTimeoutError("expected response"),
                True,
                str(ConnectTimeoutError("expected response"))
            ),
            "website2": Website(
                "website2", "https://mockWebsite2.com", 200, False, InterruptedError("Interruption error")
            ),
            "website3": Website(
                "website3", "https://mockWebsite3.com", 200, False, InterruptedError("Interruption error")
            )
        }

        verify_responses_func = Mock(
            return_value = tested_websites_with_responses
        )

        print_error_message_func = Mock()

        lambda_handler(verify_responses_func, print_error_message_func=print_error_message_func)

        website = print_error_message_func.call_args_list[0].args[0]

        for n in range(2, 4):
            self.assertEqual(website[f"website{n}"].name, f"website{n}")
            self.assertEqual(website[f"website{n}"].url, f"https://mockWebsite{n}.com")
            self.assertEqual(str(website[f"website{n}"].expected_response), "200")
            self.assertEqual(website[f"website{n}"].received_expected_response, False)
            self.assertEqual(str(website[f"website{n}"].actual_response), "Interruption error")


if __name__ == "__main__":
    unittest.main()
