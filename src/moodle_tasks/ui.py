"""Identidad visual de la terminal; no se imprime en el transporte MCP."""

from enum import Enum

from rich.console import Console, Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text


class ConnectionState(Enum):
    NOT_STARTED = "Sin iniciar"
    CONNECTED = "Conectado"
    PROBLEMS = "Con problemas"


GLYPHS = {
    "M": ("#   #", "## ##", "# # #", "#   #", "#   #"),
    "O": (" ### ", "#   #", "#   #", "#   #", " ### "),
    "D": ("#### ", "#   #", "#   #", "#   #", "#### "),
    "L": ("#    ", "#    ", "#    ", "#    ", "#####"),
    "E": ("#####", "#    ", "#### ", "#    ", "#####"),
}
RED_GRADIENT = ("#ff9d62", "#ff805b", "#ff6555", "#ed4b52", "#d6374b")


def clean_display(value: str) -> str:
    return "".join(character for character in value if character.isprintable())


def logo() -> Text:
    text = Text()
    for row, color in enumerate(RED_GRADIENT):
        pixels = " ".join(GLYPHS[letter][row] for letter in "MOODLE").replace("#", "█")
        text.append(pixels, style=color)
        if row < len(RED_GRADIENT) - 1:
            text.append("\n")
    return text


def show_dashboard(
    username: str | None = None,
    state: ConnectionState = ConnectionState.NOT_STARTED,
    *,
    agent: str | None = None,
    detail: str | None = None,
    console: Console | None = None,
) -> None:
    console = console or Console()
    color = {ConnectionState.NOT_STARTED: "bright_black", ConnectionState.CONNECTED: "green",
             ConnectionState.PROBLEMS: "red"}[state]
    account = Text()
    account.append("Cuenta\n", style="dim")
    account.append(clean_display(username) if username else "Sin cuenta configurada", style="bold")
    account.append("\n\nEstado: ", style="default")
    account.append("● " + state.value, style="bold " + color)
    if agent:
        account.append("\nAgente: " + clean_display(agent), style="dim")
    width = min(console.width, 100)
    mark = logo() if width >= 43 else Text("MOODLE", style="bold #ff6555")
    if width >= 78:
        body = Table.grid(padding=(0, 3))
        body.add_column(width=35, no_wrap=True)
        body.add_column(ratio=1)
        body.add_row(mark, account)
    else:
        body = Group(mark, Text(""), account)
    if detail:
        body = Group(body, Text(""), Text(clean_display(detail), style="dim"))
    console.print(Panel(body, title=Text("MCP · Aula Moodle", style="bold #ff6555"),
                        border_style="#ad3945", padding=(1, 2), width=width))


def show_agent_menu(agents: dict[str, str]) -> None:
    options = Text()
    for index, label in enumerate(agents.values(), 1):
        options.append(f"  {index}  ", style="bold #ff6555")
        options.append(label + "\n")
    Console().print(Panel(options, title="¿En cuál agente quieres usar Moodle?",
                          border_style="#ad3945", width=min(Console().width, 100)))
