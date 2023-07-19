import os
from typing import Dict

import urllib3

from urllib3.exceptions import ConnectTimeoutError

http = urllib3.PoolManager()


class BaseHTTPResponse:
    status: int
    data: bytes


class Website:
    def __init__(self, name, url: str, expected_response: int | Exception, received_expected_response: bool,
                 actual_response: str | Exception | None):
        self.name = name
        self.url = url
        self.expected_response = expected_response
        self.received_expected_response = received_expected_response
        self.actual_response = actual_response


def get_response(request, url: str) -> int | Exception:
    try:
        response: BaseHTTPResponse = request("GET", url, timeout = urllib3.Timeout(5), retries = False)
        return response.status
    except Exception as e:
        return e


def verify_responses(website_to_test_expected_responses: dict[str, Website],
                     request = http.request) -> dict[str, Website]:
    for website in website_to_test_expected_responses.values():
        expected_response = website.expected_response

        match expected_response:
            case ConnectTimeoutError():
                http_status: int | Exception = get_response(request, website.url)
                if type(http_status) == ConnectTimeoutError:
                    website.received_expected_response = True
                    website.actual_response = str(website.expected_response)  # just in case there is sensitive
                    # information in error message
                else:
                    website.received_expected_response = False
                    website.actual_response = str(http_status)
            case int():
                http_status: int | Exception = get_response(request, website.url)
                website.received_expected_response = http_status == website.expected_response
                website.actual_response = str(http_status)
            case _:
                raise ValueError(f"Unrecognised expected_response: {expected_response}")

    return website_to_test_expected_responses


def print_error_message(websites: dict[str, Website], print_error = print):
    for website_name, website in websites.items():
        error_message_in_json = {
            "Status": "Failure",
            "Website": website_name,
            "Message": "This address is unexpectedly available",
            "Expected Response": str(website.expected_response),
            "Actual Response": website.actual_response
        }

        print_error(error_message_in_json)


def print_success_message(preservica_website: Website, print_error = print):
    success_message_in_json = {
        "Status": "Success",
        "Website": f"{preservica_website.name}",
        "Message": f"{preservica_website.name} returned an expected response: {preservica_website.expected_response}"
    }

    print_error(success_message_in_json)


def get_websites_with_errors(preservica_website: Website, rest_of_the_tested_websites: dict[str, Website]) -> dict[
    str, Website]:
    if preservica_website.received_expected_response:
        any_other_website_received_unexpected_response = {
            website for website in rest_of_the_tested_websites.values() if not website.received_expected_response
        }

        if any_other_website_received_unexpected_response:
            print("Preservica website timed out as expected but other test websites did not receive expected response.")
            return rest_of_the_tested_websites
        return {}
    else:
        return {preservica_website.name: preservica_website}


def lambda_handler(verify_responses_func = verify_responses, print_error_message_func=print_error_message,
                   print_success_message_func=print_success_message):
    preservica_website_name = "Preservica"
    websites_to_test_for_expected_responses: dict[str, Website] = {
        preservica_website_name: Website(
            preservica_website_name,
            os.environ["PRESERVICA_URL"],
            ConnectTimeoutError(),
            False,
            None
        ),
        "www.amazon.co.uk": Website("www.amazon.co.uk", "https://www.amazon.co.uk", 200, False, None),
        "www.nationalarchives.gov.uk": Website(
            "www.nationalarchives.gov.uk", "https://www.nationalarchives.gov.uk", 200, False, None
        )
    }

    tested_websites_with_responses: dict[str, Website] = verify_responses_func(websites_to_test_for_expected_responses)
    preservica_website: Website = tested_websites_with_responses.pop(preservica_website_name)  # this removes item
    rest_of_the_tested_websites = tested_websites_with_responses
    websites_to_log_error_msgs_for: dict[str, Website] = get_websites_with_errors(preservica_website, rest_of_the_tested_websites)

    if websites_to_log_error_msgs_for:
        print_error_message_func(websites_to_log_error_msgs_for)
    else:
        print_success_message_func(preservica_website)


if __name__ == "__main__":
    lambda_handler()
