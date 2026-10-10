"""Step 0: syntactic pre-filter (no LLM).

Rejects command shapes M3 can't reason about, before any parsing or solving:
- anything that isn't a single `kubectl` command;
- shell operators outside quotes: pipes, compound commands (&&, ||, ;), background (&),
  redirection (<, >), subshells;
- command substitution (`...` or $(...)) and multi-line input, anywhere in the string;
- interactive or stdin forms (-i, -t, --stdin, --tty, -f -);
- subcommands whose effect can't be checked: edit, debug, attach, port-forward, proxy, cp, wait, exec.

Starting rule list: Stratus App. A, Table 5. Rejecting is always the safe direction: a command
rejected here is blocked, never executed.
"""

import shlex

SHELL_OPERATOR_CHARS = set("();<>|&")

UNCHECKABLE_SUBCOMMANDS = {"edit", "debug", "attach", "port-forward", "proxy", "cp", "wait", "exec"}

INTERACTIVE_FLAGS = {"-i", "-t", "-it", "-ti", "--stdin", "--tty"}

# Global kubectl flags that take a separate value, so the value isn't mistaken for the subcommand.
FLAGS_WITH_VALUE = {"-n", "--namespace", "--context", "--kubeconfig", "--cluster", "--user", "-s", "--server"}


def tokenize(command: str) -> list[str]:
    """Split like a POSIX shell, keeping shell operators as separate tokens.

    Raises ValueError on unbalanced quotes.
    """
    lexer = shlex.shlex(command, posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    return list(lexer)


def find_subcommand(tokens: list[str]) -> str | None:
    """Return the kubectl subcommand (e.g. "scale"), skipping global flags before it."""
    skip_next = False
    for token in tokens[1:]:
        if skip_next:
            skip_next = False
            continue
        if token.startswith("-"):
            skip_next = token in FLAGS_WITH_VALUE
            continue
        return token
    return None


def check(command: str) -> str | None:
    """Return a rejection reason, or None if the command may continue to parsing."""
    if not command.strip():
        return "empty command"
    if "\n" in command or "\r" in command:
        return "multi-line command"
    if "`" in command or "$(" in command:
        return "command substitution"

    try:
        tokens = tokenize(command)
    except ValueError:
        return "unbalanced quotes"

    for token in tokens:
        if token and set(token) <= SHELL_OPERATOR_CHARS:
            return f"shell operator {token!r} (pipes, compound commands, redirects, subshells)"

    if tokens[0] != "kubectl":
        return "not a kubectl command"

    subcommand = find_subcommand(tokens)
    if subcommand is None:
        return "no kubectl subcommand"
    if subcommand in UNCHECKABLE_SUBCOMMANDS:
        return f"kubectl {subcommand} is interactive or its effect can't be checked"

    for i, token in enumerate(tokens):
        if token in INTERACTIVE_FLAGS or token.startswith(("--stdin=", "--tty=")):
            return f"interactive flag {token!r}"
        reads_stdin = token in ("-f", "--filename") and i + 1 < len(tokens) and tokens[i + 1] == "-"
        if reads_stdin or token in ("-f-", "--filename=-"):
            return "reads a manifest from stdin (-f -)"

    return None
