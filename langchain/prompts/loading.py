"""Load prompts from disk."""
import importlib
import json
import os
import tempfile
from pathlib import Path
from typing import Union

import requests
import yaml

from langchain.prompts.base import BasePromptTemplate, RegexParser
from langchain.prompts.few_shot import FewShotPromptTemplate
from langchain.prompts.prompt import PromptTemplate

URL_BASE = "https://raw.githubusercontent.com/hwchase17/langchain-hub/master/prompts/"


def load_prompt_from_config(config: dict) -> BasePromptTemplate:
    """Get the right type from the config and load it accordingly."""
    prompt_type = config.pop("_type", "prompt")
    if prompt_type == "prompt":
        return _load_prompt(config)
    elif prompt_type == "few_shot":
        return _load_few_shot_prompt(config)
    else:
        raise ValueError


def _load_template(var_name: str, config: dict) -> dict:
    """Load template from disk if applicable."""
    # Check if template_path exists in config.
    if f"{var_name}_path" in config:
        # If it does, make sure template variable doesn't also exist.
        if var_name in config:
            raise ValueError(
                f"Both `{var_name}_path` and `{var_name}` cannot be provided."
            )
        # Pop the template path from the config.
        template_path = Path(config.pop(f"{var_name}_path"))
        # Load the template.
        if template_path.suffix == ".txt":
            with open(template_path) as f:
                template = f.read()
        else:
            raise ValueError
        # Set the template variable to the extracted variable.
        config[var_name] = template
    return config


def _load_examples(config: dict) -> dict:
    """Load examples if necessary."""
    if isinstance(config["examples"], list):
        pass
    elif isinstance(config["examples"], str):
        with open(config["examples"]) as f:
            if config["examples"].endswith(".json"):
                examples = json.load(f)
            elif config["examples"].endswith((".yaml", ".yml")):
                examples = yaml.safe_load(f)
            else:
                raise ValueError(
                    "Invalid file format. Only json or yaml formats are supported."
                )
        config["examples"] = examples
    else:
        raise ValueError("Invalid examples format. Only list or string are supported.")
    return config


def _load_output_parser(config: dict) -> dict:
    """Load output parser."""
    if "output_parser" in config:
        if config["output_parser"] is not None:
            _config = config["output_parser"]
            output_parser_type = _config["_type"]
            if output_parser_type == "regex_parser":
                output_parser = RegexParser(**_config)
            else:
                raise ValueError(f"Unsupported output parser {output_parser_type}")
            config["output_parser"] = output_parser
    return config


def _load_few_shot_prompt(config: dict) -> FewShotPromptTemplate:
    """Load the few shot prompt from the config."""
    # Load the suffix and prefix templates.
    config = _load_template("suffix", config)
    config = _load_template("prefix", config)
    # Load the example prompt.
    if "example_prompt_path" in config:
        if "example_prompt" in config:
            raise ValueError(
                "Only one of example_prompt and example_prompt_path should "
                "be specified."
            )
        config["example_prompt"] = load_prompt(config.pop("example_prompt_path"))
    else:
        config["example_prompt"] = load_prompt_from_config(config["example_prompt"])
    # Load the examples.
    config = _load_examples(config)
    config = _load_output_parser(config)
    return FewShotPromptTemplate(**config)


def _load_prompt(config: dict) -> PromptTemplate:
    """Load the prompt template from config."""
    # Load the template from disk if necessary.
    config = _load_template("template", config)
    config = _load_output_parser(config)
    return PromptTemplate(**config)


def load_prompt(path: Union[str, Path]) -> BasePromptTemplate:
    """Unified method for loading a prompt from LangChainHub or local fs."""
    if isinstance(path, str) and path.startswith("lc://prompts"):
        path = os.path.relpath(path, "lc://prompts/")
        return _load_from_hub(path)
    else:
        return _load_prompt_from_file(path)


def _load_prompt_from_file(file: Union[str, Path]) -> BasePromptTemplate:
    """Load prompt from file."""
    # Convert file to Path object.
    if isinstance(file, str):
        file_path = Path(file)
    else:
        file_path = file
    # Load from either json or yaml.
    if file_path.suffix == ".json":
        with open(file_path) as f:
            config = json.load(f)
    elif file_path.suffix == ".yaml":
        with open(file_path, "r") as f:
            config = yaml.safe_load(f)
    elif file_path.suffix == ".py":
        spec = importlib.util.spec_from_loader(
            "prompt", loader=None, origin=str(file_path)
        )
        if spec is None:
            raise ValueError("could not load spec")
        helper = importlib.util.module_from_spec(spec)
        with open(file_path, "rb") as f:
            exec(f.read(), helper.__dict__)
        if not isinstance(helper.PROMPT, BasePromptTemplate):
            raise ValueError("Did not get object of type BasePromptTemplate.")
        return helper.PROMPT
    else:
        raise ValueError(f"Got unsupported file type {file_path.suffix}")
    # Load the prompt from the config now.
    return load_prompt_from_config(config)


def _load_from_hub(path: str) -> BasePromptTemplate:
    """Load prompt from hub."""
    suffix = path.split(".")[-1]
    if suffix not in {"py", "json", "yaml"}:
        raise ValueError("Unsupported file type.")
    full_url = URL_BASE + path
    r = requests.get(full_url)
    if r.status_code != 200:
        raise ValueError(f"Could not find file at {full_url}")
    with tempfile.TemporaryDirectory() as tmpdirname:
        file = tmpdirname + "/prompt." + suffix
        with open(file, "wb") as f:
            f.write(r.content)
        return _load_prompt_from_file(file)
