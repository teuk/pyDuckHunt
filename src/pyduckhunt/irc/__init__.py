"""Small, strict IRC protocol primitives used by pyDuckHunt."""

from pyduckhunt.irc.message import (
    IRCMessage,
    IRCProtocolError,
    notice_text_budget,
    parse_irc_line,
    privmsg_text_budget,
    render_irc_message,
    render_notice,
    render_notice_bounded,
    render_pong,
    render_privmsg,
    render_privmsg_bounded,
)
from pyduckhunt.irc.stream import IRCLineBuffer
from pyduckhunt.irc.socket_adapter import (
    IRCAdapterResult,
    IRCByteStream,
    IRCEndpoint,
    IRCSocketAdapter,
    IRCSocketConnector,
)
from pyduckhunt.irc.transport import (
    IRCTransport,
    IRCTransportAction,
    IRCTransportActionKind,
    IRCTransportPolicy,
    IRCTransportState,
    IRCTransportStep,
)

__all__ = [
    "IRCMessage",
    "IRCAdapterResult",
    "IRCByteStream",
    "IRCEndpoint",
    "IRCLineBuffer",
    "IRCProtocolError",
    "IRCSocketAdapter",
    "IRCSocketConnector",
    "IRCTransport",
    "IRCTransportAction",
    "IRCTransportActionKind",
    "IRCTransportPolicy",
    "IRCTransportState",
    "IRCTransportStep",
    "notice_text_budget",
    "parse_irc_line",
    "privmsg_text_budget",
    "render_irc_message",
    "render_notice",
    "render_notice_bounded",
    "render_pong",
    "render_privmsg",
    "render_privmsg_bounded",
]
