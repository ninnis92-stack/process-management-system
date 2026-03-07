from app import create_app
from app.models import SiteConfig

app = create_app()

with app.app_context():
    cfg = SiteConfig.get()
    print('Active quote set:', cfg.active_quote_set)
    print('Available sets:')
    for k, v in cfg.rolling_quote_sets.items():
        print(f'- {k} ({len(v)} lines)')
    print('\nSample lines:')
    for i, line in enumerate(cfg.rolling_quotes[:5]):
        print(f'{i+1}. {line}')
