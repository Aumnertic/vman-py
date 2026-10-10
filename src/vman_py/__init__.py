def main(argv: list[str] | None = None) -> int:
    from .cli.cli import main as cli_main

    return cli_main(argv)
