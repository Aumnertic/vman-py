"""根据 Pydantic 字段生成 argparse 参数，并校验解析结果。"""

import argparse
from collections.abc import Sequence
from typing import Any

from pydantic import BaseModel, ValidationError


def add_arguments(parser: argparse.ArgumentParser, model_cls: type[BaseModel]) -> None:
    """字段的 json_schema_extra 可声明 positional、flags、help 和 metavar。"""
    for name, field in model_cls.model_fields.items():
        metadata = field.json_schema_extra
        metadata = metadata if isinstance(metadata, dict) else {}
        required = field.is_required()
        default = field.get_default(call_default_factory=True) if not required else None
        positional = metadata.get("positional", required and "flags" not in metadata)
        help_text = metadata.get("help")
        if positional:
            options: dict[str, Any] = {
                "help": help_text,
                "metavar": metadata.get("metavar", name),
            }
            if not required:
                options.update(nargs="?", default=default)
            parser.add_argument(name, **options)
        else:
            flags = metadata.get("flags", [f"--{name.replace('_', '-')}"])
            flag_options: dict[str, Any] = {
                "dest": name,
                "default": default,
                "required": required,
                "help": help_text,
            }
            if field.annotation is bool:
                flag_options["action"] = argparse.BooleanOptionalAction
            else:
                flag_options["metavar"] = metadata.get("metavar", name.upper())
            parser.add_argument(*flags, **flag_options)


def parse[Model: BaseModel](
    model_cls: type[Model], args: Sequence[str] | None = None
) -> Model:
    parser = argparse.ArgumentParser()
    add_arguments(parser, model_cls)
    try:
        return model_cls.model_validate(vars(parser.parse_args(args)))
    except ValidationError as exc:
        parser.error(str(exc))
