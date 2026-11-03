# DataDraft

Trade rulings for Sleeper redraft leagues. It scores every remaining week with your
league's own scoring and lineup slots, then rules ACCEPT, REJECT, TOSS-UP or COUNTER.

```
python3.13 -m venv .venv && .venv/bin/pip install -e '.[dev]'

datadraft leagues <sleeper_username>          # find your league id
datadraft trade <league_id> "A, B for C"      # you send A and B, you get C
```

Your team is whichever roster holds A and B, so anyone in the league can run it.
Set `ANTHROPIC_API_KEY` to add the court's sourced for/against arguments; without it
the ruling and numbers still print. Data is cached under `~/.datadraft`.

Not supported yet: keeper/dynasty leagues, draft picks or FAAB in trades, IDP slots.
Run the tests with `.venv/bin/pytest`.
