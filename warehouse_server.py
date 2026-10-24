import json
import sys

from mcp.server.fastmcp import FastMCP

MAX_CONTAINERS = 5
MAX_BOXES = 10
MAX_LOG_EVENTS = 5

# ---------------------------------------------------------------------------
# Loading and validating the warehouse file
# ---------------------------------------------------------------------------

def fail(message):
    """Print a readable error and quit."""
    sys.exit(f"Error: {message}")


def is_int(value):
    """True for real integers. bool is a subclass of int, so rule it out."""
    return isinstance(value, int) and not isinstance(value, bool)


def load_warehouse(path):
    """Read the JSON warehouse file, check it, and return it as a dict."""
    try:
        with open(path, encoding="utf-8") as f:
            warehouse = json.load(f)
    except FileNotFoundError:
        fail(f"warehouse file not found: {path}")
    except json.JSONDecodeError as e:
        fail(f"{path} is not valid JSON ({e})")

    if not isinstance(warehouse, dict):
        fail("the top level of the warehouse file must be a JSON object")

    # Required fields with the right types.
    if not isinstance(warehouse.get("title"), str):
        fail("'title' is required and must be a string")
    containers = warehouse.get("containers")
    if not isinstance(containers, list):
        fail("'containers' is required and must be a list")
    boxes = warehouse.get("boxes")
    if not isinstance(boxes, list):
        fail("'boxes' is required and must be a list")

    # Size limits.
    if not 1 <= len(containers) <= MAX_CONTAINERS:
        fail(f"'containers' must have between 1 and {MAX_CONTAINERS} entries (found {len(containers)})")
    if len(boxes) > MAX_BOXES:
        fail(f"'boxes' can have at most {MAX_BOXES} entries (found {len(boxes)})")

    # Each container needs a unique integer id and a capacity (max number of boxes).
    capacities = {}  # container id -> capacity
    for container in containers:
        if not isinstance(container, dict) or not is_int(container.get("id")):
            fail("each container must be an object with an integer 'id'")
        container_id = container["id"]
        if container_id in capacities:
            fail(f"duplicate container id: {container_id}")
        if not is_int(container.get("capacity")) or container["capacity"] < 1:
            fail(f"container {container_id}: 'capacity' must be an integer of at least 1")
        capacities[container_id] = container["capacity"]

    # Each box needs a unique integer id, a description, and an existing container.
    seen_box_ids = set()
    box_counts = {container_id: 0 for container_id in capacities}
    for box in boxes:
        if not isinstance(box, dict) or not is_int(box.get("id")):
            fail("each box must be an object with an integer 'id'")
        box_id = box["id"]
        if box_id in seen_box_ids:
            fail(f"duplicate box id: {box_id}")
        seen_box_ids.add(box_id)
        if not isinstance(box.get("description"), str):
            fail(f"box {box_id}: 'description' is required and must be a string")
        if not is_int(box.get("container_id")) or box["container_id"] not in capacities:
            fail(f"box {box_id}: 'container_id' must be the id of an existing container")
        box_counts[box["container_id"]] += 1

    # No container may hold more boxes than its capacity.
    for container_id, count in box_counts.items():
        if count > capacities[container_id]:
            fail(f"container {container_id} is overfull: {count} boxes, capacity {capacities[container_id]}")

    return warehouse

# ---------------------------------------------------------------------------
# Server state
# ---------------------------------------------------------------------------

if len(sys.argv) < 2:
    sys.exit("Usage: python warehouse_server.py <path-to-warehouse.json>")

warehouse = load_warehouse(sys.argv[1])
event_log = []  # the last few events, shown in the terminal


def log_event(text):
    """Remember an event and redraw the terminal. Call this from every tool."""
    event_log.append(text)
    del event_log[:-MAX_LOG_EVENTS]  # keep only the newest few
    draw_display(warehouse, event_log)


# ---------------------------------------------------------------------------
# Live terminal display
# ---------------------------------------------------------------------------

def draw_display(warehouse, events=()):
    """Clear the terminal and redraw every container with its boxes.

    Each container shows one line per slot (capacity), so you can see at a
    glance how full it is. `events` is an optional list of recent log lines.
    """
    divider = "=" * 60
    print("\033[2J\033[H", end="")  # ANSI: clear screen, cursor to top-left
    print(warehouse["title"])
    print(divider)

    for container in warehouse["containers"]:
        # Boxes live in one flat list; pick out the ones in this container.
        boxes = [b for b in warehouse["boxes"] if b["container_id"] == container["id"]]
        capacity = container["capacity"]
        full = " FULL" if len(boxes) == capacity else ""
        print(f"Container {container['id']}   [{len(boxes)}/{capacity}]{full}")
        for slot in range(capacity):
            if slot < len(boxes):
                box = boxes[slot]
                print(f"  {slot + 1}. box {box['id']}: {box['description']}")
            else:
                print(f"  {slot + 1}. (empty)")
        print()

    if events:
        print(divider)
        print("Recent events:")
        for event in events:
            print(f"  {event}")
    sys.stdout.flush()


# ---------------------------------------------------------------------------
# The MCP server
# ---------------------------------------------------------------------------

mcp = FastMCP("warehouse", log_level="WARNING")


@mcp.tool()
def get_container_ids() -> str:
    """Returns the ids of each container in the warehouse, for example '{1,2,3}'."""
    ids = ",".join(str(c["id"]) for c in warehouse["containers"])
    result = "{" + ids + "}"
    log_event(f"get_container_ids: {result}")
    return result


@mcp.tool()
def check_container_box_ids(container_id: int) -> str:
    """Returns the ids of each box in the container, for example '{1,4,2}', or '{}' if there were none."""
    ids = ",".join(str(b["id"]) for b in warehouse["boxes"] if b["container_id"] == container_id)
    result = "{" + ids + "}"
    log_event(f"check_container_box_ids({container_id}): {result}")
    return result


@mcp.tool()
def get_box_description(box_id: int) -> str:
    """Returns the description of the box, or an empty string if it wasn't found."""
    result = ""
    for box in warehouse["boxes"]:
        if box["id"] == box_id:
            result = box["description"]
    log_event(f"get_box_description({box_id}): '{result}'")
    return result


@mcp.tool()
def move_box_to_container(box_id: int, container_id: int) -> str:
    """Moves the box into the container if possible. Reports success (including if the box was already there) or why it failed."""
    box = next((b for b in warehouse["boxes"] if b["id"] == box_id), None)
    container = next((c for c in warehouse["containers"] if c["id"] == container_id), None)

    if box is None:
        result = f"Failure: there is no box with id {box_id}."
    elif container is None:
        result = f"Failure: there is no container with id {container_id}."
    elif box["container_id"] == container_id:
        result = f"Success: box {box_id} was already in container {container_id}."
    else:
        contents = sum(1 for b in warehouse["boxes"] if b["container_id"] == container_id)
        if contents >= container["capacity"]:
            result = f"Failure: container {container_id} is full ({contents} of {container['capacity']})."
        else:
            box["container_id"] = container_id
            result = f"Success: moved box {box_id} into container {container_id}."

    log_event(f"move_box_to_container({box_id}, {container_id}): {result}")
    return result


if __name__ == "__main__":
    draw_display(warehouse, event_log)  # show the starting state before any tool is called
    mcp.run(transport="streamable-http")  # serves at http://localhost:8000/mcp
