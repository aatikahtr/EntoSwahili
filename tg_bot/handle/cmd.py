"""
cmd.py — mahali pa command zote za bot (BAADAYE, bado haijaunganishwa na main.py).

Wazo: command zote ziwe kwenye dict moja ("jina": function), kisha main.py
iite register_commands(application) mara moja badala ya kuandika
add_handler kwa kila command.

    from .cmd import register_commands
    register_commands(application)
"""

from telegram.ext import Application, CommandHandler

# Mfano wa baadaye:
#   from ..commands import start
#   from ..Instant_view.instant_command import instant_view_command
#   COMMANDS = {"start": start, "view": instant_view_command}
COMMANDS: dict = {}


def register_commands(application: Application) -> None:
    for name, handler in COMMANDS.items():
        application.add_handler(CommandHandler(name, handler))
