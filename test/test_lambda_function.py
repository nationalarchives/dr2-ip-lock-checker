import os
import unittest
import json
from unittest.mock import Mock
from moto import mock_aws
import boto3
from urllib3.exceptions import ConnectTimeoutError

from lambda_function import get_response, BaseHTTPResponse, Website, verify_responses, \
    send_error_messages_to_eventbridge, \
    get_websites_with_errors, run_connection_tests


def generate_list_of_websites():
    return {
        "Preservica_mock_website": Website(
            "Preservica_mock_website",
            "https://mockPreservicaWebsite.net",
            403,
            False,
            None
        ),
        "website2": Website("website2", "https://mockWebsite2.com", 200, False, None),
        "website3": Website("website3", "https://mockWebsite3.com", 200, False, None)
    }


@mock_aws
class TestIpLockChecker(unittest.TestCase):
    events_client = boto3.client("events",
                                 region_name="eu-west-2",
                                 aws_access_key_id="test-access-key",
                                 aws_secret_access_key="test-secret-key",
                                 aws_session_token="test-session-token")
    sqs_client = boto3.client("sqs",
                              region_name="eu-west-2",
                              aws_access_key_id="test-access-key",
                              aws_secret_access_key="test-secret-key",
                              aws_session_token="test-session-token")

    @staticmethod
    def set_aws_credentials():
        """Mocked AWS Credentials for moto."""
        os.environ['AWS_ACCESS_KEY_ID'] = 'testing'
        os.environ['AWS_SECRET_ACCESS_KEY'] = 'testing'
        os.environ['AWS_SECURITY_TOKEN'] = 'testing'
        os.environ['AWS_SESSION_TOKEN'] = 'testing'
        os.environ['AWS_DEFAULT_REGION'] = 'eu-west-2'

    def create_sqs_queue_and_rule(self):
        self.set_aws_credentials()
        self.events_client.put_rule(Name='test-rule', EventPattern='{"detail-type": ["DR2DevMessage"]}')
        attributes = {'FifoQueue': 'true', 'ContentBasedDeduplication': 'true'}
        sqs_queue = self.sqs_client.create_queue(QueueName='test-queue.fifo', Attributes=attributes)
        target = {'Id': 'id', 'Arn': 'arn:aws:sqs:eu-west-2:123456789012:test-queue.fifo',
                  'SqsParameters': {'MessageGroupId': 'Test'}}
        self.events_client.put_targets(Rule='test-rule', Targets=[target])
        return sqs_queue['QueueUrl']

    def delete_queue_messages(self, queue_url, receipt_handles):
        self.set_aws_credentials()
        for receipt_handle in receipt_handles:
            self.sqs_client.delete_message(QueueUrl=queue_url, ReceiptHandle=receipt_handle)

    def get_queue_messages(self, queue_url):
        self.set_aws_credentials()
        messages = []

        def process_msg(msg):
            return {
                'ReceiptHandle': msg['ReceiptHandle'],
                'ErrorMessage': json.loads(msg['Body'])['detail']['slackMessage']
            }

        msgs_response = self.sqs_client.receive_message(QueueUrl=queue_url, MaxNumberOfMessages=10)

        while 'Messages' in msgs_response:
            messages += [process_msg(msg) for msg in msgs_response['Messages']]
            msgs_response = self.sqs_client.receive_message(QueueUrl=queue_url, MaxNumberOfMessages=10)

        return messages

    @staticmethod
    def generate_expected_error_message(site_name, expected_response, actual_response, prefix="un"):
        return "\n".join((f":alert-noflash-slow: *IP lock check failure*: {site_name} is unexpectedly {prefix}available.",
                          f"*Expected Response*: {expected_response}",
                          f"*Actual Response*: {actual_response}"))

    def test_get_response_should_return_200_status(self):
        http = Mock()
        response = BaseHTTPResponse()
        response.status = 200
        http.request = Mock(
            return_value=response
        )

        http_status: int | Exception = get_response(http.request, "https://mockWebhookUrl.com")

        assert http.request.call_args[0] == ("GET", "https://mockWebhookUrl.com")
        assert http.request.call_args[1]["timeout"].connect_timeout == 5
        assert not http.request.call_args[1]["retries"]
        assert http_status == 200

    def test_get_response_should_return_exception(self):
        http = Mock()
        http.request = Mock(side_effect=ConnectTimeoutError())

        http_status: int | Exception = get_response(http.request, "https://mockWebhookUrl.com")

        with self.assertRaises(Exception) as _:
            http.request()

        self.assertEqual(type(http_status), ConnectTimeoutError)

    def test_verify_response_should_return_a_received_expected_response_of_true_and_updated_actual_values(self):
        http = Mock()
        response = BaseHTTPResponse()
        response.status = 200
        forbidden_response = BaseHTTPResponse()
        forbidden_response.status = 403
        http.request = Mock()
        http.request.side_effect = [forbidden_response, response, response]

        initial_list_of_websites = generate_list_of_websites()

        expected_website_result = {
            "Preservica_mock_website": Website(
                "Preservica_mock_website",
                "https://mockPreservicaWebsite.net",
                403,
                True,
                "403"
            ),
            "website2": Website("website2", "https://mockWebsite2.com", 200, True, "200"),
            "website3": Website("website3", "https://mockWebsite3.com", 200, True, "200")
        }

        response = verify_responses(initial_list_of_websites, request=http.request)

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
                403,
                False,
                str(200)
            ),
            "website2": Website("website2", "https://mockWebsite2.com", 200, True, "200"),
            "website3": Website("website3", "https://mockWebsite3.com", 200, True, "200")
        }

        response = verify_responses(initial_list_of_websites, request=http.request)

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
            verify_responses(initial_list_of_websites, request=http.request)

    def test_send_error_messages_to_eventbridge_should_send_error_message_to_eventbridge(self):
        queue_url = self.create_sqs_queue_and_rule()
        response = BaseHTTPResponse()
        response.status = 200

        websites = {
            "website2": Website(
                "website2", "https://mockWebsite2.com", 200, False, "ConnectTimeoutError"
            ),
            "website3": Website(
                "website3", "https://mockWebsite3.com", 200, False, "ConnectTimeoutError"
            )
        }

        send_error_messages_to_eventbridge(websites)

        expected_and_actual_responses = [
            self.generate_expected_error_message("website2", "200", "ConnectTimeoutError"),
            self.generate_expected_error_message("website3", "200", "ConnectTimeoutError")
        ]

        message_response = self.get_queue_messages(queue_url)
        self.assertEqual(message_response[0]['ErrorMessage'], expected_and_actual_responses[0])
        self.assertEqual(message_response[1]['ErrorMessage'], expected_and_actual_responses[1])

        self.delete_queue_messages(queue_url, [msg['ReceiptHandle'] for msg in message_response])

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

    def test_lambda_handler_should_call_eventbridge_with_error_message_with_preservica_website(self):
        queue_url = self.create_sqs_queue_and_rule()
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
            return_value=tested_websites_with_responses
        )

        run_connection_tests(verify_responses_func)

        msgs_response = self.get_queue_messages(queue_url)

        self.assertEqual(len(msgs_response), 1)
        expected_msg = self.generate_expected_error_message("Preservica", "expected response", "200", prefix="")
        self.assertEqual(msgs_response[0]['ErrorMessage'], expected_msg)
        self.delete_queue_messages(queue_url, [msg['ReceiptHandle'] for msg in msgs_response])

    def test_lambda_handler_should_call_eventbridge_with_other_websites(self):
        queue_url = self.create_sqs_queue_and_rule()
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
            return_value=tested_websites_with_responses
        )

        expected_message_one = self.generate_expected_error_message("website2", "200", "Interruption error")
        expected_message_two = self.generate_expected_error_message("website3", "200", "Interruption error")

        run_connection_tests(verify_responses_func)

        message_response = self.get_queue_messages(queue_url)
        self.assertEqual(message_response[0]['ErrorMessage'], expected_message_one)
        self.assertEqual(message_response[1]['ErrorMessage'], expected_message_two)


if __name__ == "__main__":
    unittest.main()
