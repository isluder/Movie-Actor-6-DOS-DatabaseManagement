"""Validated, startup-loaded switches for application features."""
from pathlib import Path

import yaml


DEFAULT_CONFIG = Path(__file__).resolve().parent.parent / 'config.yaml'
LABELS = {
    'movie_search': 'Movie Search',
    'hidden_gems': 'Hidden Gems',
    'box_office': 'Bombed at the Box Office',
    'source_differences': 'Source Differences',
    'six_degrees': 'Six Degrees',
    'interactive_graph': 'Interactive Graph',
    'dashboard': 'Dashboard Statistics',
    'sql_previews': 'SQL Previews',
    'sql_search': 'SQL Search',
    'manual_entry': 'Manual Entry',
    'similar_movies': 'Similar Movies',
    'knowledge_graph': 'Build your own knowledge graph',
}
PAGE_FEATURES = {'index': 'movie_search', 'gems': 'hidden_gems', 'bombs': 'box_office',
                 'differences': 'source_differences', 'degrees': 'six_degrees', 'similar_movies': 'similar_movies'}
ENDPOINT_FEATURES = {
    **PAGE_FEATURES,
    'knowledge_graph': 'knowledge_graph',
    'sql_search': 'sql_search', 'manual_entry': 'manual_entry',
    'connections_api': 'six_degrees',
    'expand_node_api': 'interactive_graph', 'actor_statistics_api': 'six_degrees',
}


class FeatureLoader(yaml.SafeLoader):
    """Reject duplicate keys so a typo cannot silently replace a setting."""


def _mapping(loader, node):
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node)
        if not isinstance(key, str) or key in result:
            raise ValueError('Feature configuration keys must be unique strings.')
        result[key] = loader.construct_object(value_node)
    return result


FeatureLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _mapping)


def load_features(path=DEFAULT_CONFIG, overrides=None):
    """Missing/invalid configuration is an error; omitted known keys default on."""
    try:
        with Path(path).open() as handle:
            document = yaml.load(handle, Loader=FeatureLoader)
    except (OSError, yaml.YAMLError) as error:
        raise ValueError(f'Cannot read feature configuration {path}: {error}') from error
    if not isinstance(document, dict) or set(document) != {'application_features'}:
        raise ValueError('Feature configuration requires an application_features mapping.')
    settings = document['application_features']
    if not isinstance(settings, dict) or set(settings) - set(LABELS.values()):
        raise ValueError('Unknown application feature; use the names in config.yaml.')
    flags = {key: _enabled(settings.get(label, 'Enable'), label) for key, label in LABELS.items()}
    if overrides is not None:
        if not isinstance(overrides, dict) or set(overrides) - set(LABELS):
            raise ValueError('Unknown FEATURES override.')
        flags.update({key: _enabled(value, key) for key, value in overrides.items()})
    if not flags['six_degrees']:
        flags['interactive_graph'] = False
    return flags


def _enabled(value, label):
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.casefold() in ('enable', 'disable'):
        return value.casefold() == 'enable'
    raise ValueError(f'{label}: use Enable or Disable.')
