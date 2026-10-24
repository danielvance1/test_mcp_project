
# Book MCP Server: Project Spec

This file is for Claude Code. Read it fully, then build the server it describes. The owner (Daniel) will edit the code afterward to learn how MCP works, so **clarity beats cleverness**. Comment the code generously, explaining what each MCP piece (tool, resource, prompt) is and why it exists. Keep everything in one Python file.

## Purpose

This is a toy project for learning the three core parts of an MCP server: **tools**, **resources**, and **prompts**. It is deliberately minimal. Do not add features beyond this spec (no page-jump tool, no subscriptions, no sampling, no database, no extra transports).

The server simulates a small book that a model can read. The server holds one piece of state: the current page number. The model turns pages with tools, reads pages with a tool, and can look up the table of contents as a resource. A user-triggered prompt tells the model how to navigate to a chapter.

## The three MCP pieces in this project

| Piece | Name | Who controls it | What it does |
|---|---|---|---|
| Resource | `book://contents` | The app (Claude Code) | The table of contents, one chapter per line. Never changes while the server runs. |
| Tool | `turn_page_right` | The model | Moves forward one page. Reports success or failure. |
| Tool | `turn_page_left` | The model | Moves back one page. Reports success or failure. |
| Tool | `get_page_number` | The model | Returns the current page number and the total page count. |
| Tool | `read_page` | The model | Returns the text of the current page. |
| Prompt | `go_to_chapter(ch_name)` | The user | Returns instructions (with the table of contents embedded) telling the model how to reach a chapter. |

There is intentionally **no** "go to page N" tool. Reaching a page means calling the turn tools repeatedly. That is the point of the prompt: it teaches the model a multi-step procedure using only the minimal tools.

## Book file format (JSON)

Books are written as simple JSON files. The server loads one at startup.

```json
{
  "title": "The Tiny Book",
  "chapters": [
    { "name": "Chapter 1", "page": 1 },
    { "name": "Chapter 2", "page": 4 },
    { "name": "Chapter 3", "page": 6 }
  ],
  "pages": [
    "Page one text.",
    "Page two text.",
    "Page three text.",
    "Page four text.",
    "Page five text.",
    "Page six text."
  ]
}
```

### Fields

- `title` (string, required): The book's title. Shown in the terminal display.
- `chapters` (array, required): The table of contents. Each entry has:
  - `name` (string): The chapter's name, for example `"Chapter 2"` or `"The Storm"`.
  - `page` (integer): The 1-based page number where the chapter starts.
- `pages` (array of strings, required): The text of each page, in order. **Page numbers are 1-based**: `pages[0]` is page 1, `pages[1]` is page 2, and so on.

### Validation rules

When loading, check all of these and exit with a clear, human-readable error message if any fail:

1. The file exists and is valid JSON.
2. `title`, `chapters`, and `pages` are all present and have the right types.
3. `pages` has between **1 and 20** entries (20 is the hard maximum).
4. Every chapter `page` is an integer between 1 and the number of pages.
5. Chapter names are unique, ignoring case.

Chapters do not need to be sorted, but the contents resource should list them sorted by page number.

## Server state

- `current_page`: integer, starts at **1** when the server starts.
- The loaded book (title, chapters, pages).
- A short in-memory log of the last 5 events (for the live display), such as "turn_page_right: success, now on page 3".

## Tools: behavior

All tools return plain strings. Turn tools must clearly say whether the action worked, so the model never has to guess.

- `turn_page_right()`
  - If not on the last page: increment `current_page` and return `"Success: turned right. Now on page N of TOTAL."`
  - If on the last page: leave the state unchanged and return `"Failure: already on the last page (page TOTAL). Cannot turn right."`
- `turn_page_left()`
  - If not on page 1: decrement `current_page` and return `"Success: turned left. Now on page N of TOTAL."`
  - If on page 1: leave the state unchanged and return `"Failure: already on the first page (page 1). Cannot turn left."`
- `get_page_number()`
  - Returns `"Current page: N of TOTAL."`
- `read_page()`
  - Returns `"Page N: <text of current page>"`

Every tool call (successful or not) should add an entry to the event log and refresh the terminal display.

## Resource: behavior

- URI: `book://contents`
- Returns the table of contents as plain text, one chapter per line, in the form `<name>: <page>`, sorted by page number. For the example book:

```
Chapter 1: 1
Chapter 2: 4
Chapter 3: 6
```

- Set the MIME type to `text/plain`.

## Prompt: behavior

- Name: `go_to_chapter`
- Argument: `ch_name` (string), the chapter the user wants.
- The server builds the message at request time and **embeds the table of contents directly in the text**. This is deliberate: it makes the prompt work even if the client never loads resources, and it shows that prompts can be dynamic.
- The returned text should say roughly this (reword as needed, but keep the procedure):

```
Here is the table of contents for the book:

<contents text>

The user wants to go to the chapter "<ch_name>".
1. Find that chapter in the table of contents (ignore case). If it does not exist, tell the user and stop.
2. Call get_page_number to see which page you are on.
3. Call turn_page_right or turn_page_left repeatedly until you reach the chapter's page. Check the success or failure result of each turn.
4. Call read_page to confirm you arrived, then tell the user which page you are on.
```

## Live terminal display

The goal is for Daniel to watch the book state change in his terminal while the model works.

- The server runs over **streamable HTTP**, not stdio. With stdio, the client launches the server as a hidden background process and the display would never be visible, and stdout is reserved for the protocol anyway.
- Run it in its own terminal with a command like `python book_server.py books/example.json`.
- After every tool call, clear the terminal (ANSI escape `\033[2J\033[H`) and redraw:
  - The book title.
  - `Page N of TOTAL`.
  - The current page's text, in a simple box or between divider lines.
  - The last 5 events from the log, newest last.
- Draw once at startup too, so the initial state is visible.
- Keep the web server's own logging quiet (warning level) so it does not scramble the display.

## Technical requirements

- Python 3.10 or newer.
- Use the official MCP Python SDK (`pip install "mcp[cli]"`, or `uv add "mcp[cli]"`) and its `FastMCP` helper (`from mcp.server.fastmcp import FastMCP`).
- Register pieces with the decorators `@mcp.tool()`, `@mcp.resource("book://contents")`, and `@mcp.prompt()`.
- Run with `mcp.run(transport="streamable-http")`. The endpoint is normally `http://localhost:8000/mcp`. Confirm the exact URL against the installed SDK's behavior or docs before writing the connection instructions.
- The book path comes from the first command-line argument (`sys.argv[1]`). If it is missing, print a usage message and exit.
- Single file: `book_server.py`.
- Also create `books/example.json` containing a small valid book of about 8 pages and 3 chapters, so the server works immediately.

## Connecting from Claude Code

Add a short "How to run" section to the end of this project's README or the top comment of `book_server.py`:

1. Start the server in one terminal: `python book_server.py books/example.json`
2. In another terminal, register it: `claude mcp add --transport http book http://localhost:8000/mcp`
3. In Claude Code, run `/mcp` to confirm it is connected.
4. The prompt shows up as a slash command, `/mcp__book__go_to_chapter`. Type it, then give the chapter name.
5. The resource can be attached by typing `@` and picking `book:book://contents`.

## Testing without an AI

Also document how to test with the MCP Inspector: `npx @modelcontextprotocol/inspector`. Connect it to the running server and try the tools, resource, and prompt by hand. This shows what each piece does on its own, with no model involved.

## Out of scope

No page-jump tool, no resource subscriptions, no authentication, no editing of the book, no saving state between runs, no multiple books at once, and no extra dependencies beyond the MCP SDK.

## How to run

> **Use the venv's Python.** The MCP SDK is installed only inside `.venv`, so a bare `python` or `python3` fails with "No module named mcp" (and on some systems `python` doesn't exist at all). Either run `.venv/bin/python ...` or activate the venv first with `source .venv/bin/activate`. Anywhere this README says `python book_server.py`, use one of those.

Setup (once): create a virtual environment and install the SDK. The code uses `FastMCP`, which was renamed in MCP SDK 2.x, so pin the 1.x series:

```
python3 -m venv .venv
.venv/bin/pip install "mcp[cli]<2"
```

1. Start the server in its own terminal (it shows a live view of the book):
   `.venv/bin/python book_server.py books/example.json`
   (or run `source .venv/bin/activate` first and use `python` instead of `.venv/bin/python`)
2. In another terminal, register it: `claude mcp add --transport http book http://localhost:8000/mcp`
3. In Claude Code, run `/mcp` to confirm it is connected.
4. The prompt is a slash command: type `/mcp__book__go_to_chapter`, then give the chapter name.
5. Attach the resource by typing `@` and picking `book:book://contents`.

## Testing without an AI (MCP Inspector)

1. Keep the server running, then in another terminal run: `npx @modelcontextprotocol/inspector`
2. In the Inspector page, set the transport to **Streamable HTTP**, the URL to `http://localhost:8000/mcp`, and click **Connect**.
3. Try each piece by hand:
   - **Tools** tab: list tools and run `turn_page_right`, `turn_page_left`, `get_page_number`, `read_page`. Watch the server terminal update.
   - **Resources** tab: read `book://contents`.
   - **Prompts** tab: pick `go_to_chapter`, enter a chapter name, and see the text the server returns.
