import sys
from pydantic import BaseModel

def _inspect_model(model_cls):
    fields = model_cls.model_fields
    positions = []
    flags = []

    for field_name, field_info in fields.items():
        if field_info.annotation is bool:
            flags.append(field_name)
        elif field_info.is_required():
            positions.append(field_name)

    return positions, flags

def _parse_argv(raw_args: list[str], bool_flags: list[str]):
    options: dict[str, str | bool] = {}
    positional = []
    i = 0
    while i < len(raw_args):
        arg = raw_args[i]
        if arg.startswith("--"):
            body = arg[2:]
            if "=" in body:
                key, value = body.split("=", 1)
                options[key] = value
                i += 1
            elif body.startswith("no-") and body[3:] in bool_flags:
                options[body[3:]] = False
                i += 1
            elif body in bool_flags:
                options[body] = True
                i += 1
            else:
                if i + 1 >= len(raw_args):
                    raise ValueError(f"Missing value for option {body}")
                options[body] = raw_args[i + 1]
                i += 2
        else:
            positional.append(arg)
            i += 1
    return options, positional

def parse(model_cls, args = None) -> BaseModel:
    positions, flags = _inspect_model(model_cls)
    raw_options, raw_positional = _parse_argv(
       args if args is not None else sys.argv[1:], flags
   )
    data = {}
    for i, name in enumerate(positions):
        if i < len(raw_positional):
            data[name] = raw_positional[i]

    data.update(raw_options)

    return model_cls(**data)


if __name__ == "__main__":
    class Args(BaseModel):
        name: str
        count: int = 1
        verbose: bool = False

    args = parse(Args)
    print(args)