"""
Book MCP Server: a toy server for learning the three core MCP pieces.

    - RESOURCE  book://contents       (read-only data the app can attach)
    - TOOLS     turn_page_right, turn_page_left, get_page_number, read_page
                                      (actions the model can call)
    - PROMPT    go_to_chapter         (a canned instruction the user triggers)

HOW TO RUN
    1. Start the server in its own terminal (it shows a live view of the book):
           .venv/bin/python book_server.py books/example.json
       (or activate the venv first with `source .venv/bin/activate`
       and then run `python book_server.py books/example.json`)
    2. In another terminal, register it with Claude Code:
           claude mcp add --transport http book http://localhost:8000/mcp
    3. In Claude Code, run /mcp to confirm it is connected.
    4. The prompt is a slash command: type /mcp__book__go_to_chapter and
       then give a chapter name.
    5. Attach the resource by typing @ and picking book:book://contents
"""

import json
import sys

from mcp.server.fastmcp import FastMCP

MAX_PAGES = 20
MAX_LOG_EVENTS = 5


# ---------------------------------------------------------------------------
# Loading and validating the book file
# ---------------------------------------------------------------------------

def fail(message):
    """Print a readable error and quit."""
    sys.exit(f"Error: {message}")


def load_book(path):
    """Read the JSON book file, check it, and return it as a dict."""
    try:
        with open(path, encoding="utf-8") as f:
            book = json.load(f)
    except FileNotFoundError:
        fail(f"book file not found: {path}")
    except json.JSONDecodeError as e:
        fail(f"{path} is not valid JSON ({e})")

    if not isinstance(book, dict):
        fail("the top level of the book file must be a JSON object")

    # Required fields with the right types.
    if not isinstance(book.get("title"), str):
        fail("'title' is required and must be a string")
    if not isinstance(book.get("chapters"), list):
        fail("'chapters' is required and must be a list")
    pages = book.get("pages")
    if not isinstance(pages, list) or not all(isinstance(p, str) for p in pages):
        fail("'pages' is required and must be a list of strings")

    # Page count limits.
    if not 1 <= len(pages) <= MAX_PAGES:
        fail(f"'pages' must have between 1 and {MAX_PAGES} entries (found {len(pages)})")

    # Each chapter needs a name and a valid page; names must be unique.
    seen_names = set()
    for chapter in book["chapters"]:
        if not isinstance(chapter, dict) or not isinstance(chapter.get("name"), str):
            fail("each chapter must be an object with a string 'name'")
        page = chapter.get("page")
        # bool is a subclass of int in Python, so rule it out explicitly.
        if not isinstance(page, int) or isinstance(page, bool):
            fail(f"chapter '{chapter['name']}': 'page' must be an integer")
        if not 1 <= page <= len(pages):
            fail(f"chapter '{chapter['name']}': page {page} is outside 1-{len(pages)}")
        key = chapter["name"].lower()
        if key in seen_names:
            fail(f"duplicate chapter name (ignoring case): '{chapter['name']}'")
        seen_names.add(key)

    return book


# ---------------------------------------------------------------------------
# Server state
# ---------------------------------------------------------------------------

if len(sys.argv) < 2:
    sys.exit("Usage: python book_server.py <path-to-book.json>")

book = load_book(sys.argv[1])
total_pages = len(book["pages"])
current_page = 1   # 1-based, like the page numbers in the book file
event_log = []     # the last few events, shown in the terminal


def log_event(text):
    """Remember an event and redraw the terminal. Called by every tool."""
    event_log.append(text)
    del event_log[:-MAX_LOG_EVENTS]  # keep only the newest few
    draw_display()


def draw_display():
    """Clear the terminal and redraw the book's current state."""
    divider = "-" * 60
    print("\033[2J\033[H", end="")  # ANSI: clear screen, cursor to top-left
    print(book["title"])
    print(f"Page {current_page} of {total_pages}")
    print(divider)
    print(book["pages"][current_page - 1])
    print(divider)
    print("Recent events:")
    for event in event_log:
        print(f"  {event}")
    sys.stdout.flush()


def contents_text():
    """The table of contents as text, one 'name: page' line per chapter."""
    chapters = sorted(book["chapters"], key=lambda c: c["page"])
    return "\n".join(f"{c['name']}: {c['page']}" for c in chapters)


# ---------------------------------------------------------------------------
# The MCP server
# ---------------------------------------------------------------------------

# log_level="WARNING" keeps the web server quiet so it doesn't scramble the display.
mcp = FastMCP("book", log_level="WARNING")


# RESOURCE: data that the *app* (Claude Code) decides to load into context,
# for example when the user attaches it with @. It is identified by a URI.
# This one never changes while the server runs.
@mcp.resource("book://contents", mime_type="text/plain")
def contents() -> str:
    """The book's table of contents, one chapter per line."""
    return contents_text()


# TOOLS: actions the *model* decides to call. The docstring is what the model
# reads to decide when to use each tool, so write it for the model.
@mcp.tool()
def turn_page_right() -> str:
    """Turn forward one page. Reports whether it worked."""
    global current_page
    if current_page < total_pages:
        current_page += 1
        result = f"Success: turned right. Now on page {current_page} of {total_pages}."
    else:
        result = f"Failure: already on the last page (page {total_pages}). Cannot turn right."
    log_event(f"turn_page_right: {result}")
    return result


@mcp.tool()
def turn_page_left() -> str:
    """Turn back one page. Reports whether it worked."""
    global current_page
    if current_page > 1:
        current_page -= 1
        result = f"Success: turned left. Now on page {current_page} of {total_pages}."
    else:
        result = "Failure: already on the first page (page 1). Cannot turn left."
    log_event(f"turn_page_left: {result}")
    return result


@mcp.tool()
def get_page_number() -> str:
    """Get the current page number and the total number of pages."""
    result = f"Current page: {current_page} of {total_pages}."
    log_event(f"get_page_number: {result}")
    return result


@mcp.tool()
def read_page() -> str:
    """Read the text of the current page."""
    result = f"Page {current_page}: {book['pages'][current_page - 1]}"
    log_event(f"read_page: page {current_page}")
    return result


# PROMPT: a reusable instruction template that the *user* picks (in Claude Code
# it appears as the slash command /mcp__book__go_to_chapter). The server builds
# the text when it is requested, so it can include live data. Here we paste the
# table of contents straight into the text, so it works even if the client
# never loads the resource above.
@mcp.prompt()
def go_to_chapter(ch_name: str) -> str:
    """Tell the model how to navigate to a chapter by name."""
    return f"""Here is the table of contents for the book:

{contents_text()}

The user wants to go to the chapter "{ch_name}".
1. Find that chapter in the table of contents (ignore case). If it does not exist, tell the user and stop.
2. Call get_page_number to see which page you are on.
3. Call turn_page_right or turn_page_left repeatedly until you reach the chapter's page. Check the success or failure result of each turn.
4. Call read_page to confirm you arrived, then tell the user which page you are on."""


if __name__ == "__main__":
    draw_display()  # show the starting state before any tool is called
    mcp.run(transport="streamable-http")  # serves at http://localhost:8000/mcp
