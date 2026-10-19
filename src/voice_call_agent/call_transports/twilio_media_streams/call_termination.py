"""Ending a phone-line call through Twilio's REST API."""

from typing import Protocol

import aiohttp
from pydantic import SecretStr

from voice_call_agent.observability.error_reporting import report_error
from voice_call_agent.observability.error_taxonomy import ErrorCode

_TWILIO_API = "https://api.twilio.com/2010-04-01"


class CallTerminator(Protocol):
    """Ends a call that is still connected after its conversation finished."""

    async def end_call(self, call_sid: str) -> None: ...


class TwilioCallTerminator:
    """Sets the call to `completed`. Failures are logged, never raised: the call is over anyway."""

    def __init__(
        self,
        account_sid: str,
        auth_token: SecretStr,
        timeout_seconds: float,
        *,
        api_base_url: str = _TWILIO_API,
    ) -> None:
        self._account_sid = account_sid
        self._api_base_url = api_base_url
        self._auth_token = auth_token
        self._timeout = aiohttp.ClientTimeout(total=timeout_seconds)

    async def end_call(self, call_sid: str) -> None:
        url = f"{self._api_base_url}/Accounts/{self._account_sid}/Calls/{call_sid}.json"
        auth = aiohttp.BasicAuth(self._account_sid, self._auth_token.get_secret_value())
        try:
            async with (
                aiohttp.ClientSession(timeout=self._timeout) as http,
                http.post(url, data={"Status": "completed"}, auth=auth) as response,
            ):
                if response.status >= 400:
                    report_error(
                        ErrorCode.TWILIO_HANGUP_FAILED, call_id=call_sid, status=response.status
                    )
        except (aiohttp.ClientError, TimeoutError) as error:
            report_error(ErrorCode.TWILIO_HANGUP_FAILED, error=error, call_id=call_sid)
