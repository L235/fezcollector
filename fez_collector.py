VERSION = "0.3"
print(f"fez_collector {VERSION} initialising...")
import ssl
from re import search, compile, RegexFlag
from contextlib import redirect_stderr
from os import devnull, environ
from sys import exit, exc_info, stderr
from datetime import datetime
from json import loads
from time import sleep

from irc.client import Reactor, ServerConnectionError
from irc.connection import Factory
from irccodes import colored

from pywikibot.comms.eventstreams import EventStreams
from pywikibot import Site, Page

TARGET = environ.get("FEZ_COLLECTOR_TARGET")
NICKNAME = environ.get("FEZ_COLLECTOR_NICKNAME") or environ.get(
    "FEZ_COLLECTOR_USERNAME"
)
USERNAME = environ.get("FEZ_COLLECTOR_USERNAME")
PASSWORD = environ.get("FEZ_COLLECTOR_PASSWORD")
CLOAK = environ.get("FEZ_COLLECTOR_CLOAK")
CONFIG_PAGE = environ.get("FEZ_COLLECTOR_CONFIG_PAGE")
USE_SASL = environ.get("FEZ_COLLECTOR_USE_SASL") == "true"
ZWS = "\u200c"
CLOAK_ERROR_MSG = (
    "Hmmm - I don't seem to have my cloak, something's gone wrong. Exiting!"
)
STALENESS_THRESHOLD_SECONDS = 2 * 60 * 60

print(f"Using SASL? {USE_SASL}")

# pywikibot / config setup
site = Site("en", "wikipedia")
config_page = Page(site, CONFIG_PAGE)
config = loads(config_page.get())

PAGE_INCLUDE_PATTERN = (
    compile(f"({'|'.join(config['pageIncludePatterns'])})", RegexFlag.IGNORECASE)
    if len(config["pageIncludePatterns"]) > 0
    else None
)
PAGE_EXCLUDE_PATTERN = (
    compile(f"({'|'.join(config['pageExcludePatterns'])})", RegexFlag.IGNORECASE)
    if len(config["pageExcludePatterns"]) > 0
    else None
)
SUMMARY_INCLUDE_PATTERN = (
    compile(f"({'|'.join(config['summaryIncludePatterns'])})", RegexFlag.IGNORECASE)
    if len(config["summaryIncludePatterns"]) > 0
    else None
)
SUMMARY_EXCLUDE_PATTERN = (
    compile(f"({'|'.join(config['summaryExcludePatterns'])})", RegexFlag.IGNORECASE)
    if len(config["summaryExcludePatterns"]) > 0
    else None
)

USER_EXCLUDE_LIST = config["userExcludeList"]
USER_INCLUDE_LIST = config["userIncludeList"]


def format_message(_change):
    actor = f"{colored(_change['user'], 'Green', padding=ZWS)}"
    if _change["type"] == "log":
        link = f"https://{_change['server_name']}/w/index.php?title=Special:Log&logid={_change['log_id']}"
        return f"{actor} {_change['log_action_comment']} {link}"

    target = f"{colored('[[','Grey', padding='')}{colored(_change['title'].strip(), 'Orange', padding='')}{colored(']]:','Grey', padding='')}"
    _comment = f"{colored(_change['comment'], 'Cyan', padding='')}"
    link = f"https://{_change['server_name']}/w/index.php?diff={_change['revision']['new']}"
    return f"{actor} edited {target} {_comment} {link}"


def command_handler(c, e):
    _msg = e.arguments[0]
    if _msg == "!fezquit":
        c.privmsg(
            TARGET,
            colored(
                "Failsafe command used, quitting - will be back shortly...",
                "Light Red",
                padding="",
            ),
        )
        c.disconnect()
    if _msg == "!ping":
        c.privmsg(TARGET, colored("pong", "Pink", padding=""))


def join_handler(c, e):
    source = e.source
    target = e.target
    if USERNAME in source and CLOAK not in source:
        print(CLOAK_ERROR_MSG)
        c.disconnect(CLOAK_ERROR_MSG)
    print(f"Joined {target}!")


def nick_handler(c, e):
    print("Nickname in use, changing...")
    if NICKNAME != USERNAME:
        c.nick(NICKNAME)
    else:
        c.nick(f"{USERNAME}_")


def connect_handler(c, e):
    print(f"Joining target channel {TARGET}...")
    irc_c.join(TARGET)


def disconnect_handler(c, e):
    print("IRC disconnect - exiting...")
    raise SystemExit()


def event_logger(c, e):
    print(f"Event received: {e}", file=stderr)


def ping_handler(c, e):
    c.pong(e.target)


# EventStreams setup
stream = EventStreams(
    streams=["recentchange", "revision-create"], since=datetime.now().isoformat()
)
stream.register_filter(server_name="en.wikipedia.org")

# IRC setup
ssl_factory = Factory(wrapper=ssl.wrap_socket)
reactor = Reactor()
try:
    irc_c = reactor.server().connect(
        "irc.libera.chat",
        6697,
        USERNAME,
        username=USERNAME,
        password=PASSWORD,
        connect_factory=ssl_factory,
        sasl_login=(USERNAME if USE_SASL else None),
    )
except Exception as exc:
    print(exc_info()[1])
    raise SystemExit() from exc


irc_c.add_global_handler("welcome", connect_handler)
irc_c.add_global_handler("nicknameinuse", nick_handler)
irc_c.add_global_handler("pubmsg", command_handler)
irc_c.add_global_handler("join", join_handler)
irc_c.add_global_handler("disconnect", disconnect_handler)
irc_c.add_global_handler("ping", ping_handler)
irc_c.add_global_handler("all_events", event_logger, -10)

reactor.process_once()

# We do this as the EventStreams API dumps a metric crapload of 'errors' to stderr
with redirect_stderr(open(devnull, "w", encoding="utf-8")):
    for change in iter(stream):
        reactor.process_once()

        timestamp = float(change["timestamp"])
        now = datetime.now().timestamp()

        if (now - STALENESS_THRESHOLD_SECONDS) > timestamp:
            continue

        title = change["title"]
        user = change["user"]
        comment = (
            change["log_action_comment"]
            if "log_action_comment" in change
            else change["comment"]
        )

        # Exclude rules - if any of these match, we're done
        if (
            user in USER_EXCLUDE_LIST
            or (
                PAGE_EXCLUDE_PATTERN is not None and search(PAGE_EXCLUDE_PATTERN, title)
            )
            or (
                SUMMARY_EXCLUDE_PATTERN is not None
                and search(SUMMARY_EXCLUDE_PATTERN, comment)
            )
        ):
            continue

        # Include rules - if any of these match, we post
        if (
            user in USER_INCLUDE_LIST
            or (
                PAGE_INCLUDE_PATTERN is not None and search(PAGE_INCLUDE_PATTERN, title)
            )
            or (
                SUMMARY_INCLUDE_PATTERN is not None
                and search(SUMMARY_INCLUDE_PATTERN, comment)
            )
        ):
            msg = format_message(change)
            if len(msg) < 512:
                irc_c.privmsg(TARGET, msg)
            else:
                print(f"Message greater than 512 characters, unable to send: {msg}")
