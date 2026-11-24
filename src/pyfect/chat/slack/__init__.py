"""The Slack adapter for ``pyfect.chat`` (Effect's ``@effect/chat-slack``):
``slack_chat`` registers the adapter and serves the Events API and
Interactivity routes; ``slack_web_api`` is the minimal Web API client it is
built on, for methods the adapter has no op for."""

from pyfect.chat.slack import slack_chat, slack_web_api
from pyfect.chat.slack.slack_chat import SlackAttachFailed, SlackChat, SlackPostOptions
from pyfect.chat.slack.slack_web_api import SlackWebApi

__all__ = [
    "SlackAttachFailed",
    "SlackChat",
    "SlackPostOptions",
    "SlackWebApi",
    "slack_chat",
    "slack_web_api",
]
