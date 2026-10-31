# Config changes
## 2026-10-30 08:50 PT - moderate loosening of soft entry thresholds (paper only, user approved)
Based on near-miss data (last 6h single-check blockers: liquidity 54, volume_1h 49, socials 15).
- MIN_VOL_H1 (1h volume bar): 40,000 -> 28,000 USD (fresh-momentum coins still get 60% of bar = 16,800)
- MIN_LIQ (min liquidity): 25,000 -> 18,000 USD (unknown liquidity still fails closed)
- MIN_SCORE (analyst entry score): 0.60 -> 0.55
Unchanged: mint/freeze authority, honeypot, rug/dev/bundle/sniper/copycat checks, MAX_TOP10 25%, socials,
day loss limit (-15%), MAX_PER_HOUR 4, sizing 10%, stop -8%, trail. Backup: ../backup_pre_loosen_20261030_085039

## 2026-10-30 08:58 PT - FOMO mode on v3x practice desk only (paper, user approved)
Trigger: v3x has no new entry for 20 min. Soft bars then scale to 85% of base, -10% every further 10 min, down to 55%.
Floors: 1h volume >= $12,000, liquidity >= $10,000, score >= 0.45. Unknown data still fails closed.
Hard checks never relaxed (mint/freeze, honeypot, rug/dev history, bundles, snipers, copycats, top10 25%, price impact, dump pattern, structure, fresh holders).
FOMO trades: size 0.15 (half of v3x 0.3), stop -5%, take profit +8%, exit if not up 3% after 10 min, council >= 0.40, EV > 0, max 2 FOMO coins waiting.
Tagged fomo:true; learning weight 0.25 (vs v3x 0.5). v3 main + other desks unchanged. Day loss limit / max per hour unchanged. Code: fomo.py. Backup: ../backup_pre_fomo_20261030_085726

## 2026-10-30 09:01 PT - Scout boosts feed + read-only Fomo wallet watch (paper only)
- Scout now also polls DexScreener token-boosts/top/v1 (already had token-profiles/latest + token-boosts/latest). Solana only.
  Boosted coins (seen in a boosts feed in the last hour) get +0.03 analyst score. All hard safety checks unchanged.
- wallet_watch.py: public wallet 19rLqxcgPCcbVEVhVEUB5d8G5WD13kUnirywGq3FCVc read via public RPC every 60s
  (getTokenAccountsByOwner for Token + Token-2022, getSignaturesForAddress). No keys/signing/transactions.
  Buy/add -> Telegram note with RYDER paper read + coin sent to Scout (full checks). Sell/trim -> Telegram note.
  Top 15 holdings worth >= $5 added to existing holdings watch (first baseline silent).
- data.json versions now include v3b + v3x (labels); v3x trades appear in opens/closed tagged "· v3x practice" / "· v3x FOMO".

## 2026-10-30 09:20 PT - upgrades 261-360 (brain7.py, paper only). Backup: ../backup_pre261_20261030_091004
New module brain7.py (state in brain7.json). Hooks in runner.py (evaluate fast path, score layer, entry-wait checks, council debate, sizing, exits, jobs, heartbeat "b7"), executor.py (review + why line), alerts.py (why sentence + hold/peak on exits), feed.py (ws watchdog 300s->120s), brain3.py (weekly lessons).
Behaviour changes on v3 main: fast path kills (honeypot shape, thin pool, scam names, wash shape, fuzzy copycat, same-name relaunch after rug); pregrad skip (pump.fun mcap $55-90k) and 15-min theme cooldown after rug exits (soft, not final);
serial launcher (>=6 coins/24h kill, >=3 -0.06); single wallet >10% kill; brain7 score layer bounded -0.15..+0.12; entry wait: fast-track at 20-60s if buyers confirmed, kill on spike-fade / early sellers / no buyers / liq -15% / one-candle volume / -12% off wait high / far above 1h avg;
after +30% m5 launch candle buy only the first 5-20% dip (waits up to 210s); borderline council 0.50-0.62 with analyst/risk split -> RYDER decides on price action; one RYDER confidence (270) drives size 0.4-1.0x (max 1.3x only after 30+ trades & >=50% wins);
portfolio: max 2 open per theme, open risk <= 6% equity, +10% day or -8% from equity peak -> half size, last hourly slot for conf >= 70%, size <= 1% of pool, overnight/weekend 0.8x;
exits: first partial at +15% (was +20%), trail tightens with profit (x0.8 at +30%, x0.65 +60%, x0.5 +100%, floor 3.5%), regime trail (risk-off x0.8, hot x1.15), buy-fade exit, flat time-stop 12/20/25 min by regime (+-4%), dev wallet check every 10s;
market dump pause 20 min (SOL -3%/1h or 3 of last 5 exits stops/rugs in 30 min) on main + v3x. Learning: per-signal / hour / source / dex / age-bucket win rates, calibration, MAE/MFE, exit-reason P&L, mistake labels (all bounded).
281/282: nightly 03:20 PT regret+replay can move liquidity/volume bars 5% (floors 15k / 22k, ceilings 25k / 40k, max once per 6h per rule); auto-revert if main P&L since change < -5% of start. Hard safety checks are never changed.

## 2026-10-30 09:50 PT - upgrades 361-400 (brain8.py, paper only). Backup: ../backup_pre361_20261030_094223
BUG FIX 361: brain2/brain4 self-tuned thresholds were overriding the approved bars at startup (runtime was vol $36k / liq $25k, not $28k / $18k). Now capped at approved values (brain8.APPROVED); self-tune can only go lower within floors.
Fixes: 362 wash_shape false positives on young coins (identical 5m/1h/6h windows) - needs distinct windows now; 363 thin_pool ignores dust/curve pools (<$2k liq or DBC/launchlab), left to liquidity check.
Main-desk patience relax (367/373/378/385): idle 60 min -> soft bars x0.9, 120 min -> x0.85, after 6 PM with <3 trades x0.8; overnight (0-7h) vol bar x0.85; score bar 0.55 -> 0.52 after 120 min idle.
Floors: vol $20k, liq $14k, score 0.52. Resets on next main trade. Hard safety checks never relaxed.
Other: projected 1h volume for pairs <60 min when buys>sells in 5m (364); pump.fun curve liquidity proxy = 20% mcap cap $40k (388, approx); socials soft (-0.05) when liq>=25k & vol>=1.5x bar (366);
5 rechecks for young/unknown pairs (365); GeckoTerminal trending + top-volume discovery every 2 min (374/375); migration rechecks +2/+6 min (377); second chance for scores within 0.05 of bar after 5 min (372);
strong score (>=0.65) entry at 60s (368); pending cap 8 (380); council near-miss 0.55-0.60 with conf>=0.6 and no veto -> half-size starter (381); min paper fill $5 (382); add-on at +4% (383).
Diagnostics: per-gate funnel in heartbeat b8, hourly 'funnel' event, over-blocking detector, funnel line in recap/weekly.

## 2026-10-30 09:56 PT - upgrades 401-440 (brain9.py, paper only). Backup: ../backup_pre401_20261030_095118
Fixes: 401/403 pressure gate killed on a 1-trade sell surplus (e.g. 645b/703s); now kill only if 5m sells >1.3x buys (10+ sells) or 1h sells >1.4x buys, else graded +-0.03 score.
402 (approx data fix): pump.fun-origin mints on canonical PumpSwap migration pools (pump_fun_amm) no longer fail lp_locked on RugCheck's 0% reading (LP held/burned by pump program). All other LP rules unchanged.
Decision: parabolic (+60% 5m), 1h dump -30% w/o bounce, <50 trades/1h, fading coin (h6 avg > 2x h1) rejected; regime score adj (risk-off -0.02, hot +0.01); regime max-open cap wired (2/3/4);
max 2 trades per coin per day, blacklist after 2 stop-outs; re-entry after stop if price reclaims entry with buyers within 20 min; tie-break due coins by confidence.
Exits: +40% within 5 min -> partial; once +12% stop >= +3%; main breakeven after +8%; FOMO breakeven+ after +5%; thin pool (<$20k) stop -6%; momentum stall (>=+8% peak, -6% off peak, m5 red) sell; max hold 90 min if not trailing; liq -15% since entry -> stop -3%.
Learning: exits re-priced 15 min later (exit rules that keep selling before +20% runs are skipped after 8 samples); price 2 min after entry tunes entry delay 45-120s; vol/liq margins at entry recorded; FOMO trades learn at 0.25 weight; 14-day half-life decay nightly 03:40.
Speed: pending checks 5s -> 3s; RugCheck reports cached 60s across rechecks.

## 2026-10-30 12:27 PT - upgrades 441-490 (brain10.py, paper only). Backup: ../backup_pre441_20261030_122431
Main-desk bars ($28k vol / $18k liq / 0.55 score + idle loosen) and all hard rug/safety checks UNCHANGED. Re-checked coins go through the full normal evaluate().
441-450 near-miss watch: volume/liquidity kills with >=30% of vol bar or >=50% of liq bar (or boosted/trending) watched 45 min (max 120 coins); any safety kill removes it.
Re-priced every ~30s (batched); re-queued for full evaluation when 1h vol >= 90% of bar (or accel >= 0.55 and vol >= 60%) AND liq >= 90% of bar; max 3 re-queues, 2 min apart; dropped if -35% from first look.
Acceleration score = 5m run-rate vs 1h avg, 5m buy share, 5m price (parabolic >+60% discounted), hour-volume growth between polls.
451/452 faster scans: 2+ watched coins accelerating -> scan every 10s, 1 -> 20s.
453 score nudge -0.02..+0.03 from acceleration (474: scaled 0.5x-1.5x by accel-trade win rate after 10 trades).
461-468 feeds: DexScreener boost amount / repeat boosts / paid profiles and GeckoTerminal repeat-trending tracked; bounded -0.03..+0.03 (big boost on weak volume = paid hype -0.03; trending 3+ polls in 30 min +0.02).
471-478 learning: near-misses re-priced at 30/60 min; per kill reason count of skipped coins that ran +30% / fell -30% (diagnostic only, no auto bar changes); nightly 14-day decay 03:45.
479-482 exits (main + v3x): liquidity <70% of entry -> sell; 5m sells >=2.5x buys (15+) under +2% -> sell; held 8+ min, +3..+15%, 5m vol <25% of hour avg & m5 red -> sell; FOMO gave back a +6% peak to <+1% -> sell. All gated by the 412 exit-rule regret filter.
487-490 reliability: brain10 jobs run off the positions thread, single-instance, 5 failures -> 5-min backoff; heartbeat block b10.

## 2026-10-30 14:50 PT - upgrades 491-515 (common.py http layer + brain11.py, paper only). Backup: ../backup_pre491_20261030_144501
No trading bars or safety checks changed.
491-499 HTTP: per-host spacing (GeckoTerminal 2.2s, DexScreener 0.25s, RugCheck 0.5s); after a 429 the host cools down 10s doubling to 300s (DexScreener capped 20s so exits keep prices), reset on success;
GET TTL cache (new_pools 45s, trending/top-volume 150s, token info 15 min, token price 20s, boosts/profiles 60s); while cooling, the last good response (<=15 min) is served; a thread never waits >20s in the queue.
506-510 hang diagnostics: positions/scan loops stamp liveness; independent watchdog dumps all thread stacks to hang.log if positions is silent 60s or scan 150s (max once/10 min). Reason: unexplained stale-heartbeat restarts at 13:26 and 13:40 PT.
511-515 health: heartbeat block b11 (per-host ok/err/latency, 429 count, cooldowns, cache hits, stale serves, loop ages, stall counts).

## 2026-10-30 14:55 PT - upgrades 516-531 (brain12.py + brain10/brain7 fixes, paper only). Backup: ../backup_pre516_20261030_144711
No bars changed. 516-518: near-miss records now keep how close the coin was to each bar (vol/liq as % of bar) and the best of the 30/60-min re-prices; watchlist + pending outcomes saved to brain10.json every ~2 min and restored on restart (were lost on every restart).
519-530 bar advisor (SUGGEST ONLY, never applies): per bar, bands 90-100/75-90/60-75/30-60% of bar; a band "costs winners" if 15+ coins, >=25% ran +30% within 60 min, and winners > dumps. Hourly 'bar_advice' log event, "Bar check" line in the morning recap, full tables in heartbeat b12.
Caveat: near-misses stopped at the first failing gate, so their later safety checks never ran; win counts are an upper bound.
531 fix: "best skipped coin" ignored readings above +5000% (recap showed an impossible +122,013,411,206% for 'Pum Coin').

## 2026-10-30 14:55 PT - FOMO floors lowered (v3x practice desk ONLY, Braydon approved). Backup: ../backup_pre_fomo4k_20261030_145313
fomo.py: volume floor $12k -> $4k, liquidity floor $10k -> $6k; step-down every 10 min after 20 idle min now 0.85 / 0.70 / 0.55 / 0.40 / 0.25 / 0.15 of the base bar (was 0.85 down to 0.55 in 0.10 steps).
Sizing: half size (0.15) unchanged; coins with 1h volume under $12k trade at quarter size (0.075). Stop -5%, TP +8%, 10-min flat exit, 0.25 learning weight, score floor 0.45 all unchanged.
Main desk bars and every rug/safety check unchanged.
## 2026-10-30 14:58 PT - Market mood fix (data side only, app untouched)
Cause: extras.regime() fetched SOL change from DexScreener once per ~10 min; any failure (DexScreener now intermittently 429s) left mood 'unknown' and SOL 1h/24h empty until the next try, with no fallback.
Fix: checked every minute off the positions thread; refresh every 5 min, retry 60s after a failure; CoinGecko fallback (24h; 1h keeps last good value); last good value kept up to 1h. Mood rules unchanged.
Follow-up 15:06 PT: CoinGecko fallback now uses market_chart (days=1) so it gives both SOL 1h and 24h (DexScreener's SOL read was failing on 429s every time, leaving 1h empty).

## 2026-10-30 17:02 PT - upgrades 532-537 (freeze work, paper only). Backup: ../backup_pre532_20261030_165957
hang.log caught one stall (15:54:21 PT, positions loop silent 81s) but the dump fired after the loop had already recovered, so no stuck stack was captured.
Likely causes fixed: (a) heavy learning jobs ran ON the positions thread (brain.audit/train every 900 ticks, brain7 nearmiss_learn/agent_accuracy/best_skipped every 900 ticks, nightly regret_tune) -> now background, single-instance (534/535);
(b) the positions thread queued behind scan threads in the DexScreener rate limiter (931s total throttle wait since 15:06) -> open-position price calls skip the queue (537).
532/533: every positions-loop step is timed; >3s logs 'slow_step' and is listed in heartbeat b11 (slow, slow_by_step, in_progress). 536: stall dump now at 30s and names the step in progress.
No bars or safety checks changed.
538 (17:07 PT): brain3.holdings_watch iterated HOLD while another thread filled it at startup ('dictionary changed size during iteration'); now iterates a snapshot.

## 2026-10-30 20:58 PT - REVERT 402 (Braydon approved) + skipped_chased log. Backup: ../backup_pre_revert402_20261030_205650
filters.py: removed the pump.fun canonical-pool LP shortcut; brain9.pump_canonical() now always False. LP-lock rule is strict again on all desks (pump_fun_amm with RugCheck 0% locked -> lp_locked FAIL; smoke-tested).
Reason: CHIPCR and Qcatom passed only via this shortcut and both went to $0 liquidity within ~30 min.
runner.py: entry-wait rejections for pumping >10% now also log a 'skipped_chased' event (wait price, price now, move %, limit, score). Logging only, no behavior change.

## 2026-10-30 21:05 PT - agent council upgrades (brain13.py, paper only, lower-only). Backup: ../backup_pre_agents_20261030_205851
Six agents (brain2.votes): scout (source/pattern/momentum), filter (verified safety checks/holder concentration), analyst (score/win prob/smart wallets/theme),
executor (liquidity/price impact/buy pressure), risk (open positions/day P&L/market regime/creator history, has veto), logger (hour-of-day win rate/lessons).
New (only lower votes or add a reject; no bars or hard checks loosened):
- Shared rug memory: every scored coin's fingerprint (dex, pair age, liq band, mcap/liq band, one-burst trading, source) is graded dead/alive by detect.sweep_dead 30+ min later.
  risk -0.20 when >=50% of 4+ look-alikes died (-0.35 at >=70%, can trigger the existing RISK VETO); scout -0.15 when a source's rug rate >=60% over 8+ coins.
- filter -0.25 wash flag: identical 5m and 1h buy/sell counts on a pair older than 10 min.
- executor -0.15 when market cap > 20x liquidity (hard to exit). analyst -0.08 when already +25% in 5m.
- Disagreement check before buys: an agent with trust >=1.0 voting <0.40 -> consensus must be min_consensus +0.05 or the buy is rejected (logged).
- 'council_votes' log event per council decision: each agent's vote, trust, weight share and reason.
- Shadow self-grading: council decisions re-priced 60 min later (right = vote>=0.5 matches +10% with liq>=$5k); folded into brain2 trust at 0.25 weight. Logger vote reason shows shadow accuracy after 20+ grades.

## 2026-10-30 21:08 PT - FREEZE ROOT CAUSE fixed (logger.py)
hang.log 20:30 PT caught the positions loop stuck 125s inside logger.conn() on the schema PRAGMA/ALTER. Every DB connection (thousands/hour, 10+ threads + publisher) re-ran
CREATE TABLE IF NOT EXISTS / PRAGMA table_info in rollback-journal mode, so threads queued on the SQLite lock (up to the 30s busy timeout, repeatedly).
Fix: desk.db switched to WAL (readers never block the writer; persists in the file), synchronous=NORMAL, schema checked once per process. 200 connections now take ~5 ms.

## 2026-10-30 ~22:30 PT — six upgrades (brain14.py, backtest14.py) — PAPER ONLY
Main-desk bars unchanged ($28K vol / $18K liq / 0.55). No safety check loosened. No new app panels.
1. Backtest (`python3 backtest14.py` -> reports/backtest14.json). 5,483 killed coins re-priced ~1h later over 13.6h: 9.5% died (-80%+), 6.4% ran +30%.
   - Scout source death-rate: old trigger 60% never fired. Tightened to 30% (brain13): flags 178 coins, 29.8% died vs 8.8% of the rest; clipped 1h move -29.8% vs -9.7%.
     Source memory seeded from that history (pumpportal-ws 33% dead, pumpportal-migration 34%, geckoterminal 8.5%).
   - Wash flag / 5m>25% / mcap>20x liq / rug fingerprint / disagreement: NOT backtestable yet (pair shape was never stored; no council decisions since the agent upgrade).
     Snapshots are now stored at council time and re-priced at 60 min (table `snapshots`); rerun backtest14.py later.
   - Copycat by symbol only: flags 23% of coins, 12.3% died vs 8.7% -> kept as a soft Risk nudge only.
2. Mood-aware FOMO exits (v3x FOMO trades): risk-off SOL -> TP +6%, stop -4%; hot -> past +8% hold with trailing floor max(+5%, peak-3%); neutral unchanged (+8%).
   Main desk exits already mood-aware (brain7.regime_trail) -> untouched.
3. Copycat-rug memory: dead coins (counterfactual -90%, detect.sweep_dead) -> rug_assets img/name14/sym/creator. Risk vote: same image or creator -0.35 (usually veto),
   same name -0.15, symbol only -0.08. Exact image match also hits the existing more.precheck hard kill (stricter).
4. Fomo wallet hints: wallet buys -> also 45-min brain10 re-check watch; Scout's reason notes "your Fomo wallet holds it". No score bump, no trading from it. Read-only.
5. Telegram buy alerts (main + FOMO) list the six agent votes with short reasons.
6. Freeze watchdog (b14-watchdog): positions loop silent 90s -> starts a fresh positions thread (old one exits on its next loop via a generation token),
   max once per 5 min, logged to hang.log + 'selfheal' event. brain10 background jobs stuck >10 min are freed. Scan loop still relies on supervisor (180s heartbeat).

## 2026-10-30 ~22:40 PT — stall root cause, scan watchdog, RPC 403 fix, rugcheck retry — PAPER ONLY
- 9:37 PM PT stall: NOT a RYDER loop. Events table has a 151s gap 21:35:11 -> 21:37:42 across ALL threads (scan + positions); the separate
  publisher process also missed its 21:37:56 push (21:34:53 -> 21:40:12); brain11's 10s watchdog thread itself did not run until 140s.
  The whole box/process was frozen (CPU/VM pause). Positions thread stack at dump time was idle in time.sleep.
  Now: brain14 watchdog measures its own sleep drift; >45s overrun = 'process_pause' (hang.log + event), loop stamps reset, no pointless restart.
  brain11 skips stack dumps right after a pause; scan dump threshold 150s -> 100s.
- Scan loop moved off the main thread into 'scan_loop' (generation token). scan() silent 120s -> fresh scan thread (max 1 per 10 min), hang.log.
  Main thread now only supervises. `python3 runner.py N` (cycles) still runs inline.
- Fomo wallet 403: publicnode returns 403 "Request blocked" for getTokenAccountsByOwner (mainnet-beta works). common.rpc now cools off an
  endpoint+method after 403/429/blocked (2,4,8..30 min). wallet_watch backs off 2/4/8/15 min on failure, keeps last balances (no fake 'sold'), marks 'stale'.
- rugcheck retry: 62 coins/24h passed volume+liquidity and died only on 'lp_locked: unknown (rugcheck unavailable)' (report not generated yet).
  They are re-run through the full fail-closed evaluate() at +150s and +300s (max 2). No check loosened.
- Not done on purpose: faster entry (90s wait is also the orderflow/lower-lows rug watch -> shortening it weakens safety);
  agent self-calibration already exists (brain13 shadow grades -> trust), but 0 council decisions so far, so nothing to calibrate.

## 2026-10-30 ~22:50 PT — rugcheck outage found, candidate priority — PAPER ONLY
- ROOT CAUSE of no trades tonight: rugcheck.xyz /report (and /report/summary) returns 400 "unable to generate report" for EVERY token, even BONK,
  since ~7 PM PT (lp_locked 'rugcheck unavailable' kills per hour: 16:00 2/17, 18:00 4/9, 19:00 10/10, 20:00 24/24, 21:00 20/20, 22:00 21/21; 0 before 4 PM).
  rugcheck host 1 ok / 87 errors since 10:23 PM. Fail-closed stays (no check loosened) -> nothing that passes volume+liquidity can buy until rugcheck is back
  or a vetted replacement LP-lock/insider source is added (needs Braydon's call).
- brain14.rc_probe: BONK probe every ~10 min, 'rugcheck_health' event on change, heartbeat b14.rugcheck. rugcheck retries pause while it is down.
- Scan ordering: candidates evaluated strongest-first (1h volume + liquidity vs bar, capped; re-checks / Fomo-wallet hints first). Ordering only.
- Data too thin (0 council votes, 0 snapshots, 0 v3x/FOMO trades ever): per-agent learning and FOMO confidence sizing NOT built.

## 2026-10-30 ~23:20 PT — rugcheck BACKUP safety check (approved by Braydon 22:51 PT) + brakes/stats — PAPER ONLY
- rcfallback.py + fbchain.py: used ONLY when rugcheck.xyz returns no report. On-chain (free RPC, read-only) rugcheck-shaped report -> every downstream
  filters.check gate runs unchanged. Strict rules:
  * LP: pump.fun bonding curve verified on-chain (PDA owned by pump program, complete=0) = no withdrawable LP; PumpSwap pool verified (owner pAMM,
    base=mint, quote=SOL) and LP burned = 1 - LP mint supply / pool.lp_supply >= 95%. Reversed/non-canonical pools (SOL as base: the CHIPCR/Qcatom
    pattern) -> reject. Any other pool holding >= max($1k, 10%) of the coin's liquidity -> reject (NIO case). Other DEXes -> reject.
  * Token-2022: only metadataPointer/tokenMetadata extensions; metadata update authority set -> mutable -> reject; any transfer-fee config -> reject.
    Legacy SPL: Metaplex is_mutable read on-chain. Mint/freeze authority as before.
  * Holders: every token account via getProgramAccounts; pool/curve vaults excluded; top-10 <= 25%, identical-bag/sniper checks as before.
  * Dev history, bundle check, holder cluster, wash: MUST return pass in backup mode (unknown -> reject; rugcheck path tolerated unknown).
  * Backup-approved trades: 0.5x size (brain15).
- Validation (reports/validate_fb.json, validate_fb.py; coins re-read NOW, hours after the original decision):
  155 coins rugcheck flagged/rugged -> 115 rejected, 40 passed. All 77 LP flags rejected, CHIPCR + Qcatom rejected, dev_rugs 2/2, honeypot 1/1.
  The 40 passes were all holder-based flags (top10 20, bundle_sizes 9, insiders 9, snipers 2) whose holder makeup has changed since; in live mode
  those coins also face the strict on-chain bundle/cluster checks — not retro-testable.
  22 coins that passed rugcheck -> 14 pass, 8 reject (3 reversed PumpSwap pools, CHIPCR/Qcatom (correct: rugged), BONK + WIF (Orca/Raydium not supported),
  ANONPAD (bug: $0 side pool) fixed).
- brain15: trade-quality stats per desk (win rate, expectancy, profit factor, payoff, max drawdown, avg hold) in heartbeat + data.json 'trade_quality'
  (data only, no panel). Down-only size brakes: equity >10% under peak -> 0.5x (off again within 5%); 20+ trades and rolling-20 expectancy < 0 -> 0.5x.

## 2026-10-31 ~00:20 PT — copy desk + grading + scale-outs + exposure cap + MEV fills + serial launcher (approved by Braydon) — PAPER ONLY
- brain16.py: paper copy desk 'vC' ($300 start). Wallets (public third-party trackers that match them on-chain to Fomo trades:
  fomoradar.io/traders/<name>, fomoapi.io/traders/oinkersrus; each confirmed active on-chain):
  bystevenr AH75Bn6QHSt5K2Ad4p1otns3JTwpSJWZTwiwKWNhmnKx · vvvvvvvvvv 4Bc4Ue2G37zoQCiksAvwMgXQQJFKcYQThnoHPKizAmWB ·
  G41T3R98 4t5cayg6FDWkyQwyuYq9DqcRRCQ7e6JXyf9J7f2wfZQW · awtorkowski7 7zs3Cda5C8XWadmFKKfuPyXpo78F5AFY6RXQ3Ec5p9k7 ·
  SavageCountry CdMRJEA33ee3JsLjMNkc9LohTkczSpom63vkyRu988qa · OinkersRUs DPAN2Vig8BokpQCCu4mtV1mTWYLS7ktKe1hHKVBcsayL.
  tikitikitrader NOT found (only shortened GDpq…jQrN public) -> not used.
  Read-only balance polling (one wallet / 20s). Buy -> 30s delay -> chase guard +10% -> full filters.check (all safety; FOMO floors $4K/$6K) -> 5% size.
  Wallet sells fraction f -> vC sells f (>=90% = full exit). Only wallets graded 'good' are copied; graded from last 40 txs + live, every 6h.
- Scale-outs: v3x +40% / +80% (25% each, after its existing first partial); vC 25% at +20/+50/+100%. Main desk untouched.
- Per-coin exposure cap: 12% of desk equity per coin incl. adds (all v3+ desks).
- MEV/sandwich model: +0.15% + size/liquidity (cap 2%, unknown liq 1%) on every v3+ paper buy, add, sell and partial, on top of slippage + fee.
- Serial launcher (onchain.dev_history): 5+ prior launches with <=10% graduated off the bonding curve -> fail (same fail-closed rules as the existing dev check).
- executor.partial now takes a fraction (default 0.5 = unchanged behaviour). Copy trades appear in existing Trades lists as 'SYM · copy <trader>' (data only).
