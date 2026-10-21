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
