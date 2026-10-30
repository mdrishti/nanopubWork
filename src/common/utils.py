import datetime
from urllib.parse import quote


def normalize_so_id(raw_id: str) -> str:
    # Strips a leading "SO:" (case-insensitive) so callers can safely
    # concatenate onto the SO namespace URI without producing a malformed
    # URI like ".../term/SO:1000032" instead of ".../term/1000032".
    raw_id = str(raw_id).strip()
    return raw_id[3:] if raw_id.upper().startswith("SO:") else raw_id


# Formats the URI part by replacing spaces with underscores and encoding special characters.
def format_uri(uri_part: str) -> str:
    encoded_string = quote(uri_part, safe="")
    return encoded_string


# Appends the current date and time followed by the message to the log file.
def print_to_log(message, filename="output.log"):
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_entry = f"[{timestamp}] {message}\n"
    with open(filename, "a") as log_file:
        log_file.write(log_entry)
