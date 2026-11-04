# Strategy Desk in the RYDER Hub

Open the existing Hub at /RYDER-AI/#layout. The Overview card contains a compact
map to Radar, Trades, Research and More. All backend behavior is simulated.

Momentum and pullback setups use recorded five-minute activity. A pullback also
requires a rising hour and a controlled five-minute dip. The ordinary safety and
wait gates remain mandatory. Active setups require a newer same-pool quote,
sustained buying and a readable round-trip route at confirmation. Pullbacks
must have bounced at least 0.5% from the signal. Simulated execution still uses
the desk's fee and slippage model; the route check is a proxy, not a guaranteed
fill. Standard signals retain the existing entry path.

At the first profit target the main desk takes one third on strong buying, two
thirds when sells dominate, or half with inconclusive tape. Adaptive trailing
width feeds the existing risk manager; the recorded stop only ratchets upward.
Second looks are bounded retries for missing volume or near-threshold liquidity
and volume. A retry performs the normal checks, not an automatic entry.

Radar shows pending signals and the next scheduled rechecks. Trades plots
recorded fills and a horizontal peak level; peak time is not inferred. Research
shows realized results and drawdown for completed main-desk openings over the
last seven days. Historical entries without strategy labels remain unclassified.
Overview's Installed badge requires both publisher schema and runner release
evidence. Latest snapshot time and installed revision are in Hub layout.
