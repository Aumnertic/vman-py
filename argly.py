from pydantic import BaseModel, Field
import sys
def _inspect_model(model_cls):
    fields = model_cls.model_fields
    positions = []
    options = []
    flags = []

    for field_name, field_info in fields.items():
        if field_info.annotation is bool:
            flags.append(field_name)
        elif field_info.is_required():
            positions.append(field_name)
        else:
            options.append(field_name) 

    return positions, options, flags

def _parse_argv(raw_args: list[str]) -> tuple[dict[str, str], list[str]]:
    options = {}
    positional = []
    i = 0
    while i < len(raw_args):
        arg = raw_args[i]
        if arg.startswith("--"):
            if i + 1 < len(raw_args) and not raw_args[i + 1].startswith("--"):
                options[arg[2:]] = raw_args[i + 1]
                i += 2
            else:
                options[arg[2:]] = True
                i += 1
        else:
            positional.append(arg)
            i += 1
    return options, positional

def parse(model_cls, args = None) -> BaseModel:
    positions, options, flags = _inspect_model(model_cls)
    raw_options, raw_positional = _parse_argv(args or sys.argv[1:])
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