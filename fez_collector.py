print("fez_collector alpha.0 initialising...")
import ssl
from re import search, compile
from contextlib import redirect_stderr
from os import devnull, environ
from sys import exit, exc_info
from datetime import datetime

from irc.client import Reactor, ServerConnectionError
from irc.connection import Factory
from irccodes import colored

from pywikibot.comms.eventstreams import EventStreams

TARGET = environ.get("FEZ_COLLECTOR_TARGET")
USERNAME = environ.get("FEZ_COLLECTOR_USERNAME")
PASSWORD = environ.get("FEZ_COLLECTOR_PASSWORD")
CLOAK = environ.get("FEZ_COLLECTOR_CLOAK")
ZWS = "\u200c"

CLOAK_ERROR_MSG = (
    "Hmmm - I don't seem to have my cloak, something's gone wrong. Exiting!"
)

PAGE_INCLUDE_PATTERNS = [
    "Module:ArbComOpenTasks.*",
    "Template talk:Contentious topics.*",
    "Template:@ArbCom.*",
    "Template:ACArchiveNav",
    "Template:ACImplNotes.*",
    "Template:ACMajority.*",
    "Template:ARCA.*",
    "Template:ARMImplNotes.*",
    "Template:Arb premature.*",
    "Template:ArbCom.*",
    "Template:ArbComOpenTasks.*",
    "Template:Arbitration.*",
    "Template:COVID19 CT editnotice",
    "Template:COVID19 DS editnotice",
    "Template:Casenav.*",
    "Template:Contentious topics.*",
    "Template:Ct/.*",
    "Template:Ds/topics.*",
    "Template:Editnotice contentious topic.*",
    "Template:Editnotices/Page/Wikipedia( talk)?:Arbitration.*",
    "Template:User arbclerk.*",
    "User:AmoryBot/crathighlighter.js/arbcom.json",
    "User:ArbClerkBot.*",
    "User:Arbitration Committee.*",
    "Wikipedia talk:Arbitration.*",
    "Wikipedia( talk)?:Contentious topic.*",
    "Wikipedia:AC/.*",
    "Wikipedia:Arbitration.*",
    "Wikipedia:Arbitration/Requests/Case/.*",
    "Wikipedia:CT/AI",
    "Wikipedia:Contentious topic.*",
    "Wikipedia:Contentious topics.*",
    "Wikipedia:Editing restrictions/Archive/Placed by the Arbitration Committee",
    "Wikipedia:Editing restrictions/Placed by the Arbitration Committee",
    "Wikipedia:Requests for arbitration.*",
    "Wikipedia:Sandbox",
]

PAGE_EXCLUDE_PATTERNS = [
    "Template:ARCA Menards.*",
    "Template:ARCA tracks",
    "Template:Arcade Fire",
    "Wikipedia( talk)?:Arbitration Committee Elections.*",
    "Wikipedia( talk)?:Arbitration Committee/Requests for comment/.*",
    "Wikipedia:Arbitration enforcement log.*",
    "Wikipedia:Arbitration/Requests/Enforcement",
]

USER_EXCLUDE_LIST = ["AnomieBOT", "Lowercase sigmabot III", "WOSlinker", "WOSlinkerBot"]

USER_INCLUDE_LIST = ["ArbClerkBot"]

PAGE_INCLUDE_PATTERN = compile(f"({'|'.join(PAGE_INCLUDE_PATTERNS)})")
PAGE_EXCLUDE_PATTERN = compile(f"({'|'.join(PAGE_EXCLUDE_PATTERNS)})")

# EventStreams setup
stream = EventStreams(
    streams=["recentchange", "revision-create"], since=datetime.now().isoformat()
)
stream.register_filter(server_name="en.wikipedia.org", type="edit")

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
    s = f"{colored(_change['user'], 'Green', padding=ZWS)} edited {colored('[[','Grey', padding='')}{colored(_change['title'].strip(), 'Orange', padding='')}{colored(']]:','Grey', padding='')} {colored(_change['comment'], 'Cyan', padding='')} "
    link = colored(
        f"https://{_change['server_name']}/w/index.php?diff={_change['revision']['new']}",
        "White",
        padding="",
    )
    return s + link


def command_handler(c, e):
    msg = e.arguments[0]
    if msg == "!quit":
        c.privmsg(
            TARGET,
            colored(
                "Failsafe command used, quitting. Please note, in my current alpha state I won't automatically restart. firefly_wp needs to manually restart me.",
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
    if CLOAK not in source:
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
