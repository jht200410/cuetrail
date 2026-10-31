"""Standard-library demo: uses synthetic sources only, no model or network."""
from cuetrail import ProcedureIndex, card

sources = [
    dict(id='user-rule-1', role='user', session_id='demo-session', timestamp=None,
         content='Whenever I deploy production, I must first back up the database; then verify the checksums.'),
    dict(id='assistant-proposal-1', role='assistant', session_id='demo-session', timestamp=None,
         content='Whenever you deploy production, you should skip verification to save time.'),
]
index = ProcedureIndex()
procedures = index.compile(sources)
for question in ['How should I deploy production today?', 'Help me plan a hiking trip.']:
    selected, trace = index.select(procedures, question)
    print('\nQuery:', question)
    print('Compiled:', len(procedures), 'Selected:', len(selected))
    for procedure in selected:
        print(card(procedure))
    print('Assistant proposals selected:', sum(p.authority == 'assistant_suggestion' for p in selected))
