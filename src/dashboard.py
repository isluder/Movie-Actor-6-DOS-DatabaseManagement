"""Presentation metadata for configurable, source-aware dashboard cards."""
DEFAULTS = {
    'index': ['movies', 'actors', 'gems', 'bombs'],
    'gems': ['matches', 'average_rating', 'average_budget'],
    'bombs': ['matches', 'shortfall', 'avg_roi'],
}


def cards(catalog, result, source_label, page_type, flags):
    summary = result['summary']
    metrics = []

    def add(key, label, value, kind, scope, description, tone='gold', icon='◈'):
        if value is None:
            display = '—'
        elif kind == 'money':
            display = f'${value:,.0f}'
        elif kind == 'percent':
            display = f'{value:,.1f}%'
        elif kind == 'rating':
            display = f'{value:.2f}'
        else:
            display = f'{value:,}'
        metrics.append(dict(id=key, label=label, value=value, display=display, scope=scope,
                            description=description, tone=tone, icon=icon))

    catalog_scope = 'Entire catalog · all sources'
    source_scope = 'Entire catalog · ' + source_label
    match_scope = 'All matches · ' + source_label
    add('movies', 'Movies in catalog', catalog['movies'], 'count', catalog_scope,
        'Distinct visible movie identities across all sources.', icon='▣')
    add('actors', 'Actors in catalog', catalog['actors'], 'count', catalog_scope,
        'Distinct actor identities in the catalog.', 'blue', '◉')
    add('roles', 'Source cast roles', catalog['roles'], 'count', catalog_scope,
        'Source-labeled cast roles, including multiple roles and source memberships.', 'blue')
    add('genres', 'Genres in catalog', catalog['genres'], 'count', catalog_scope,
        'Distinct genre identities in the catalog.', 'blue')
    if flags['hidden_gems']:
        add('gems', 'Hidden Gems', catalog['gems'], 'count', source_scope,
            'Default definition: rating ≥7.4, 50–4,500 votes, and known budget ≤$35 million.', 'green', '◇')
    if flags['box_office']:
        add('bombs', 'Bombed at the Box Office', catalog['bombs'], 'count', source_scope,
            'Known revenue below known production budget, with production budget ≥$10 million.', 'red', '↘')
    add('matches', {'index': 'Matching movies', 'gems': 'Hidden Gems found', 'bombs': 'Box-office bombs found'}[page_type],
        result['total'], 'count', match_scope, 'All qualifying movies, across every results page.', icon='⌕')
    add('average_rating', 'Average rating', summary['average_rating'], 'rating', match_scope,
        'Mean known rating in the selected source across all matches; ambiguous records are excluded.', 'gold', '☆')
    add('average_budget', 'Average production budget', summary['average_budget'], 'money', match_scope,
        'Mean known production budget across all matches; unknown and zero budgets are excluded.', 'blue', '▤')
    add('total_revenue', 'Combined box-office revenue', summary['total_revenue'], 'money', match_scope,
        'Sum of known box-office revenues across all matches; unknown and zero revenues are excluded.', 'green', '↗')
    if flags['box_office']:
        add('shortfall', 'Combined production shortfall', summary['total_shortfall'], 'money', match_scope,
            'Sum of production budget minus revenue for matches below budget; this is not studio loss.', 'red', '↘')
    add('avg_roi', 'Average revenue minus budget', summary['avg_roi'], 'percent', match_scope,
        'Mean (revenue − production budget) / production budget across matches with known positive financials; not studio profit.',
        'red' if (summary['avg_roi'] or 0) < 0 else 'green', '%')
    available = {item['id'] for item in metrics}
    defaults = [key if key in available else 'matches' for key in DEFAULTS[page_type]]
    return dict(page=page_type, metrics=metrics, defaults=defaults)


def metric(key, label, value, scope, description, tone='gold', kind='count', icon='◈'):
    display = '—' if value is None else (f'{value:.2f}' if kind == 'decimal' else f'{value:,}')
    return dict(id=key, label=label, value=value, display=display, scope=scope,
                description=description, tone=tone, icon=icon)


def difference_cards(result):
    scope = 'All matching movies · every results page'
    summary = result['summary']
    descriptions = [
        ('matches', 'Movies with differences', 'matches', 'Any differing compared field, including vote counts.', 'gold'),
        ('substantive', 'Beyond vote counts', 'substantive', 'Movies with differences in title, rating, production budget, or revenue.', 'blue'),
        ('votes_only', 'Vote-count differences only', 'votes_only', 'All other compared fields agree; only the vote count differs.', 'green'),
    ]
    metrics = [metric(key, label, summary[field], scope, description, tone)
               for key, label, field, description, tone in descriptions]
    for field, label in [('title', 'Different titles'), ('vote_average', 'Different ratings'),
                         ('budget', 'Different budgets'), ('revenue', 'Different revenues'), ('vote_count', 'Different vote counts')]:
        metrics.append(metric(field, label, summary[field], scope,
            'Movies with this field differing across preserved source records. A movie can differ in multiple fields.', 'blue'))
    return dict(page='differences', metrics=metrics, defaults=['matches', 'substantive', 'votes_only'])


def degree_cards(data=None):
    data = data or {}
    scope = ('From ' + data['actor_name']) if data.get('actor_name') else 'Select a From actor'
    specs = [
        ('connected', 'Connected actors', 'Actors reachable at any distance, excluding the starting actor.', 'blue', 'count'),
        ('disconnected', 'Actors not connected', 'Other catalog actors unreachable in this selected cast network, including actors absent from this source.', 'red', 'count'),
        ('average', 'Average connection length', 'Mean shortest co-star distance to all reachable other actors, including distances beyond six. Excludes self and unreachable actors.', 'gold', 'decimal'),
        ('maximum', 'Farthest connection', 'Largest shortest co-star distance to any reachable other actor.', 'green', 'count'),
        ('within_six', 'Actors within six degrees', 'Reachable other actors at distances one through six.', 'blue', 'count'),
        ('beyond_six', 'Actors beyond six degrees', 'Reachable other actors whose shortest connection is longer than six.', 'gold', 'count'),
        ('direct_movies', 'Movies starring this actor', 'Visible movie connections in the selected cast network.', 'green', 'count'),
        ('network_actors', 'Actors in selected network', 'Catalog actors with at least one visible cast connection in the selected source network.', 'blue', 'count'),
        ('total_actors', 'Actors in catalog', 'All catalog actor identities; the starting actor is excluded from connected/disconnected counts.', 'blue', 'count'),
    ]
    return dict(page='degrees', defaults=['connected', 'disconnected', 'average', 'maximum'],
        metrics=[metric(key, label, data.get(key), scope, description, tone, kind)
                 for key, label, description, tone, kind in specs])
