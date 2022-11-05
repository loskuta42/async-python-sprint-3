import logging.config

import yaml


def get_logger_for_module(name: str) -> logging.Logger:
    with open('logging_config.yaml', 'r') as f:
        config = yaml.safe_load(f.read())
        logging.config.dictConfig(config)

    return logging.getLogger(name)
