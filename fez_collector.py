print("fez_collector alpha.0 initialising...")
import ssl
from re import search, compile
from contextlib import redirect_stderr
from os import devnull, environ
from sys import exit, exc_info
from datetime import datetime
from json import loads

from irc.client import Reactor, ServerConnectionError
from irc.connection import Factory
from irccodes import colored

from pywikibot.comms.eventstreams import EventStreams
from pywikibot import Site, Page

TARGET = environ.get("FEZ_COLLECTOR_TARGET")
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
USER_EXCLUDE_LIST = config["userExcludeList"]
USER_INCLUDE_LIST = config["userIncludeList"]

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
    )
except ServerConnectionError as exc:
    print(exc_info()[1])
    raise exit(1) from exc

irc_c.join(TARGET)


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
        print("Failsafe command used - exiting.")
        exit(1)
    if msg == "!ping":
        c.privmsg(TARGET, colored("pong", "Pink", padding=""))


def join_handler(c, e):
    source = e.source
    target = e.target
    if USERNAME in source and CLOAK not in source:
        print(CLOAK_ERROR_MSG)
        c.quit(CLOAK_ERROR_MSG)
        exit(1)
    print(f"Joined {target}!")


irc_c.add_global_handler("pubmsg", command_handler)
irc_c.add_global_handler("join", join_handler)
print("initialised!")

# We do this as the EventStreams API dumps a metric crapload of 'errors' to stderr
with redirect_stderr(open(devnull, "w", encoding="utf-8")):
    for change in iter(stream):
        title = change["title"]
        user = change["user"]
        if (
            search(PAGE_INCLUDE_PATTERN, title)
            and not search(PAGE_EXCLUDE_PATTERN, title)
            and user not in USER_EXCLUDE_LIST
        ) or user in USER_INCLUDE_LIST:
            irc_c.privmsg(TARGET, format_message(change))
        reactor.process_once()
