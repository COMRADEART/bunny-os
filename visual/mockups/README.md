# Mock-state boundary

Mock state exists only to exercise deterministic visual-review scenarios. It is
loaded exclusively when `BUNNY_VISUAL_MOCK_MODE=1`, and every consumer must keep
a permanent `VISUAL MOCK DATA` banner visible while mock state is active.

Mocks never write approval decisions, action results, credentials, provider
secrets, or release evidence. The production package task fails when mock mode
is present in its environment.
