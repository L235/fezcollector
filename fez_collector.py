VERSION = "0.2"
print(f"fez_collector {VERSION} initialising...")
import ssl
from re import search, compile
from contextlib import redirect_stderr
from os import devnull, environ
from sys import exit, exc_info
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
ZWS = "\u200c"
CLOAK_ERROR_MSG = (
    "Hmmm - I don't seem to have my cloak, something's gone wrong. Exiting!"
)

# pywikibot / config setup
site = Site("en", "wikipedia")
config_page = Page(site, CONFIG_PAGE)
config = loads(config_page.get())

PAGE_INCLUDE_PATTERN = compile(f"({'|'.join(config['pageIncludePatterns'])})")
PAGE_EXCLUDE_PATTERN = compile(f"({'|'.join(config['pageExcludePatterns'])})")
SUMMARY_INCLUDE_PATTERN = compile(f"({'|'.join(config['summaryIncludePatterns'])})")
SUMMARY_EXCLUDE_PATTERN = compile(f"({'|'.join(config['summaryExcludePatterns'])})")
USER_EXCLUDE_LIST = config["userExcludeList"]
USER_INCLUDE_LIST = config["userIncludeList"]


def format_message(_change):
    if _change["type"] == "log":
        verb = _change["log_action_comment"].split(" ")[0]
        link = f"https://{_change['server_name']}/w/index.php?title=Special:Log&logid={_change['log_id']}"
    else:
        verb = "edited"
        link = f"https://{_change['server_name']}/w/index.php?diff={_change['revision']['new']}"

    s = f"{colored(_change['user'], 'Green', padding=ZWS)} {verb} {colored('[[','Grey', padding='')}{colored(_change['title'].strip(), 'Orange', padding='')}{colored(']]:','Grey', padding='')} {colored(_change['comment'], 'Cyan', padding='')} "

    return s + link


def command_handler(c, e):
    msg = e.arguments[0]
    if msg == "!fezquit":
        c.privmsg(
            TARGET,
            colored(
                "Failsafe command used, quitting - will be back shortly...",
                "Light Red",
                padding="",
            ),
        )
        c.disconnect()
    if msg == "!ping":
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
    irc_c.join(TARGET)


def disconnect_handler(c, e):
    print("IRC disconnect - exiting...")
    exit(1)


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
        sasl_login=USERNAME,
    )
except ServerConnectionError as exc:
    print(exc_info()[1])
    raise exit(1) from exc


irc_c.add_global_handler("welcome", connect_handler)
irc_c.add_global_handler("nicknameinuse", nick_handler)
irc_c.add_global_handler("pubmsg", command_handler)
irc_c.add_global_handler("join", join_handler)
irc_c.add_global_handler("disconnect", disconnect_handler)

reactor.process_once()
print("initialised!")

try:
    # We do this as the EventStreams API dumps a metric crapload of 'errors' to stderr
    with redirect_stderr(open(devnull, "w", encoding="utf-8")):
        for change in iter(stream):
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
                or search(PAGE_EXCLUDE_PATTERN, title)
                or search(SUMMARY_EXCLUDE_PATTERN, comment)
            ):
                continue

            # Include rules - if any of these match, we post
            if (
                user in USER_INCLUDE_LIST
                or search(PAGE_INCLUDE_PATTERN, title)
                or search(SUMMARY_INCLUDE_PATTERN, comment)
            ):
                irc_c.privmsg(TARGET, format_message(change))

            reactor.process_once()
# Done to ensure we exit cleanly and the continuous job (on Toolforge) gets restarted
except Exception as err:
    irc_c.disconnect()
    print(err)
    exit(1)
