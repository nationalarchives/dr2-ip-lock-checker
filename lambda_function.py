import os
import json
import urllib3
import boto3
from urllib3.exceptions import ConnectTimeoutError

http = urllib3.PoolManager()
client = boto3.client('events', region_name="eu-west-2")


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
        response: BaseHTTPResponse = request("GET", url, timeout=urllib3.Timeout(5), retries=False)
        return response.status
    except Exception as e:
        return e


def verify_responses(website_to_test_expected_responses: dict[str, Website],
                     request=http.request) -> dict[str, Website]:
    for website in website_to_test_expected_responses.values():
        expected_response = website.expected_response

        match expected_response:
            case int():
                http_status: int = get_response(request, website.url)
                website.received_expected_response = http_status == website.expected_response
                website.actual_response = str(http_status)
            case _:
                raise ValueError(f"Unrecognised expected_response: {expected_response}")

    return website_to_test_expected_responses


def send_error_messages_to_eventbridge(websites: dict[str, Website]):
    for website_name, website in websites.items():
        prefix = "un" if website.expected_response == 200 else ""
        err_msg = (f":alert-noflash-slow: *IP lock check failure*: {website_name} is unexpectedly {prefix}available.",
                   f"*Expected Response*: {str(website.expected_response)}",
                   f"*Actual Response*: {website.actual_response}")
        detail_message = json.dumps({"slackMessage": "\n".join(err_msg)})
        entries = [{'Source': 'IPLockCheckerSlackMessage', 'DetailType': 'DR2DevMessage', 'Detail': detail_message}]
        client.put_events(Entries=entries)


def get_websites_with_errors(preservica_website: Website, rest_of_the_tested_websites: dict[str, Website]
                             ) -> dict[str, Website]:
    if preservica_website.received_expected_response:
        any_other_website_received_unexpected_response = {
            name: website for name, website in rest_of_the_tested_websites.items()
            if not website.received_expected_response
        }

        if any_other_website_received_unexpected_response:
            print("Preservica website timed out as expected but other test websites did not receive expected response.")
        return any_other_website_received_unexpected_response
    else:
        return {preservica_website.name: preservica_website}


def run_connection_tests(verify_responses_func=verify_responses):
    preservica_website_name = "Preservica"
    websites_to_test_for_expected_responses: dict[str, Website] = {
        preservica_website_name: Website(
            preservica_website_name,
            os.environ["PRESERVICA_URL"],
            403,
            False,
            None
        ),
        "www.nationalarchives.gov.uk": Website(
            "www.nationalarchives.gov.uk", "https://www.nationalarchives.gov.uk", 200, False, None
        )
    }

    tested_websites_with_responses: dict[str, Website] = verify_responses_func(websites_to_test_for_expected_responses)
    preservica_website: Website = tested_websites_with_responses.pop(preservica_website_name)  # this removes item
    rest_of_the_tested_websites = tested_websites_with_responses
    websites_to_log_error_msgs_for: dict[str, Website] = get_websites_with_errors(preservica_website,
                                                                                  rest_of_the_tested_websites)

    send_error_messages_to_eventbridge(websites_to_log_error_msgs_for)


def lambda_handler(event, context):
    run_connection_tests()
